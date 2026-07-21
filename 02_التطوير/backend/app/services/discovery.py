"""
Network discovery service.

Uses python-nmap to perform a host-discovery scan (-sn -PR) on the local subnet,
then parses the result into a list of device dicts.

The scan is blocking (nmap is a subprocess) so we run it in an executor thread
to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
from typing import TYPE_CHECKING, Any

# NOTE: `nmap` (python-nmap) is imported LAZILY inside the nmap code path, not at
# module top. nmap is an OPTIONAL scanner — the shipped default is the pure-Python
# scanner (discovery_python). A top-level import would make python-nmap a hard
# load-time dependency, so if it weren't bundled the whole app would fail to load
# ("error while loading the program"). `from __future__ import annotations` keeps
# the `nmap.PortScanner` type hints below as strings, so they don't import it.
from loguru import logger

if TYPE_CHECKING:  # type-checker only — NOT imported at runtime
    import nmap

from ..config import settings
from .discovery_python import discover_python
from .mac_vendor import enrich_vendor
from .network_utils import classify_device, get_local_subnet, normalize_mac
from .progress import scan_progress

# Ceiling for the whole nmap scan. The actual budget is derived from the host
# count (a /24 doesn't need the same wall clock as a /16), clamped to this.
DEFAULT_SCAN_TIMEOUT_SECONDS = 600  # 10 minutes (ceiling)
MIN_SCAN_BUDGET_SECONDS = 60
PER_HOST_BUDGET_SECONDS = 0.8
# Extra grace before we abandon a wedged nmap thread. nmap's own --host-timeout
# should stop it first; this only guards a truly stuck process so the request
# can't hang forever — the executor await used to be completely unbounded.
SCAN_GRACE_SECONDS = 30


class DiscoveryError(RuntimeError):
    """Raised when nmap fails to scan (e.g. nmap not installed, no admin)."""


def _scan_budget(host_estimate: int, ceiling: int) -> int:
    """Wall-clock budget for the whole scan, scaled by host count and clamped.

    A /24 gets a tight budget; a capped /16 gets the ceiling. Replaces the flat
    600s that a /24 and a /16 shared."""
    if host_estimate <= 0:
        return ceiling
    budget = host_estimate * PER_HOST_BUDGET_SECONDS
    return int(min(max(budget, MIN_SCAN_BUDGET_SECONDS), ceiling))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _nmap_available() -> bool:
    """nmap is usable only if BOTH the binary is on PATH and the python-nmap
    wrapper can be imported. Either missing -> fall back to the pure-Python scanner."""
    if shutil.which("nmap") is None:
        return False
    try:
        import nmap  # noqa: F401 — lazy: presence check only

        return True
    except ImportError:
        return False


def _choose_method() -> str:
    method = getattr(settings, "scan_method", "auto")
    if method in ("nmap", "python"):
        return method
    return "nmap" if _nmap_available() else "python"


async def scan_network(
    subnet: str | None = None,
    timeout: int = DEFAULT_SCAN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Run a host-discovery scan on the local subnet and return the parsed result.

    Uses the pure-Python scanner by default (no nmap/Npcap needed); uses nmap
    only when it is installed and selected via settings.scan_method. Returns:
      {
        "subnet": "192.168.1.0/24",
        "devices": [ {ip, mac, hostname, vendor, device_type, status}, ... ],
        "host_count": 42,
      }

    Raises DiscoveryError on failure.
    """
    target = subnet or get_local_subnet()
    method = _choose_method()
    logger.info(f"Starting host-discovery scan on {target} (method={method})")
    # NOTE: the caller owns the progress lifecycle — it calls scan_progress.begin()
    # synchronously (so the run is marked in-progress before this returns) and
    # scan_progress.finish() only AFTER the results are persisted. This function
    # just runs the scan and marks a failure.

    try:
        if method == "nmap":
            devices = await _scan_with_nmap(target, timeout)
        else:
            devices = await discover_python(target)
    except DiscoveryError as exc:
        scan_progress.fail(str(exc))
        raise
    except Exception as exc:
        scan_progress.fail(str(exc))
        raise DiscoveryError(str(exc)) from exc

    logger.info(f"Scan complete on {target}: {len(devices)} device(s) found (method={method})")
    return {
        "subnet": target,
        "devices": devices,
        "host_count": len(devices),
        "method": method,  # 'python' (bundled, no nmap) or 'nmap' — surfaced in the UI
    }


async def _scan_with_nmap(target: str, timeout: int) -> list[dict[str, Any]]:
    """nmap-based discovery (used only when nmap is installed and selected)."""
    host_estimate = 0
    try:
        import ipaddress as _ip

        net = _ip.IPv4Network(target, strict=False)
        host_estimate = max(net.num_addresses - 2, 1)
    except Exception:
        pass

    budget = _scan_budget(host_estimate, timeout)

    if host_estimate >= 1024:
        scan_progress.set_phase(
            "scanning",
            f"Probing {host_estimate:,} addresses with nmap (may take several minutes)",
        )
    elif host_estimate > 0:
        scan_progress.set_phase("scanning", f"Probing {host_estimate} addresses with nmap")
    else:
        scan_progress.set_phase("scanning", "Probing addresses with nmap")

    # Heartbeat — append a log line every 10s while nmap is running so the UI
    # shows continuous activity even when nmap itself is silent for minutes.
    # It stays informational, NOT a stall-watchdog: nmap reports nothing until it
    # returns (devices_count is 0 for the whole scan), so aborting on "no new
    # device" would false-fire on every legitimately long scan. The real bound is
    # the wall-clock ceiling on the await below.
    async def _heartbeat() -> None:
        ticks = 0
        while True:
            await asyncio.sleep(10)
            ticks += 1
            scan_progress.add(
                "scanning",
                f"Still scanning... ({ticks * 10}s elapsed, "
                f"{scan_progress.devices_count} found so far)",
            )

    heartbeat_task = asyncio.create_task(_heartbeat())
    loop = asyncio.get_event_loop()
    fut = loop.run_in_executor(None, _do_scan, target, budget)
    try:
        # Total wall-clock bound. nmap's --host-timeout is PER HOST and can't
        # bound the whole scan, and awaiting the executor directly was unbounded
        # (a wedged nmap hung the request forever, like the WUA bug). asyncio.wait
        # — not wait_for — never blocks on the uncancellable nmap thread: on
        # overrun we abandon it (it stops on its own --host-timeout) and raise.
        done, _pending = await asyncio.wait({fut}, timeout=budget + SCAN_GRACE_SECONDS)
    finally:
        heartbeat_task.cancel()

    if not done:
        raise DiscoveryError(
            f"nmap scan exceeded {budget + SCAN_GRACE_SECONDS}s and was abandoned "
            f"(the scan appears to be stuck)."
        )

    devices: list[dict[str, Any]] = fut.result()
    scan_progress.set_phase("classifying", "Classifying device types")
    return devices


# ---------------------------------------------------------------------------
# Internal — runs in executor (blocking)
# ---------------------------------------------------------------------------
def _do_scan(subnet: str, host_timeout: int) -> list[dict[str, Any]]:
    """Synchronous nmap scan. Called from a thread by ``scan_network``.

    ``host_timeout`` is the adaptive per-host cap (nmap ``--host-timeout``); the
    whole-scan wall-clock bound is enforced by the caller's ``asyncio.wait``."""
    try:
        import nmap  # lazy: the app loads even if python-nmap isn't available
    except ImportError as e:
        raise DiscoveryError("nmap غير متاح — استخدم الماسح المدمج (python) من الإعدادات.") from e
    try:
        nm = nmap.PortScanner()
    except nmap.PortScannerError as e:
        logger.exception("Could not initialize nmap PortScanner")
        raise DiscoveryError("nmap not found. Make sure Nmap is installed and on PATH.") from e

    # -sn  : ping/host-discovery scan only (no port scan)
    # NO -PR (no ARP-only): we want nmap to use its default probe set
    #                       which includes ICMP echo + TCP SYN/ACK on ports
    #                       80/443/22/3389 + ICMP timestamp. Without -PR,
    #                       nmap STILL uses ARP automatically for hosts in
    #                       the same broadcast domain, but ALSO probes
    #                       routed targets (which ARP can't reach).
    # -T4                  : aggressive timing
    # -n                   : skip nmap DNS (we do reverse-DNS ourselves)
    # --max-retries 1      : don't retry endlessly on dead hosts
    # --max-rtt-timeout    : cap per-probe round-trip time
    # --min-parallelism 64 : scan up to 64 hosts in parallel
    # --min-hostgroup 64   : group hosts to keep nmap busy
    args = (
        f"-sn -T4 -n --max-retries 1 --max-rtt-timeout 1500ms "
        f"--min-parallelism 64 --min-hostgroup 64 --host-timeout {host_timeout}s"
    )
    try:
        nm.scan(hosts=subnet, arguments=args)
    except nmap.PortScannerError as e:
        logger.exception("nmap scan failed")
        raise DiscoveryError(f"nmap scan failed: {e}") from e

    # If this scan overran and was abandoned, a newer scan may now own the
    # progress feed; only write to it while we're still the current generation.
    gen = scan_progress.generation
    devices: list[dict[str, Any]] = []
    all_hosts = nm.all_hosts()
    if all_hosts and scan_progress.generation == gen:
        scan_progress.set_phase(
            "resolving",
            f"Resolving hostnames for {len(all_hosts)} responding device(s)",
        )
    for ip in all_hosts:
        try:
            entry = _parse_host(nm, ip)
            if entry:
                devices.append(entry)
                if scan_progress.generation == gen:
                    vendor_suffix = f"({entry['vendor']})" if entry["vendor"] else ""
                    scan_progress.update_count(
                        len(devices),
                        f"Found {entry['ip']} {vendor_suffix}".strip(),
                    )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not parse host {ip}: {exc}")

    return devices


def _parse_host(nm: nmap.PortScanner, ip: str) -> dict[str, Any] | None:
    """Pull IP/MAC/hostname/vendor out of a single nmap result entry."""
    host = nm[ip]

    # MAC and vendor
    mac = ""
    vendor = ""
    addresses = host.get("addresses", {})
    if "mac" in addresses:
        mac = normalize_mac(addresses["mac"])

    vendors = host.get("vendor", {})
    if vendors:
        if mac and mac.replace("-", ":") in {k.upper() for k in vendors.keys()}:
            # Map back to the original key
            for k, v in vendors.items():
                if k.upper() == mac:
                    vendor = v
                    break
        if not vendor:
            # Use the first vendor entry as a fallback
            vendor = next(iter(vendors.values()))

    # Hostname (nmap result, fallback to reverse DNS)
    hostname = ""
    hostnames = host.get("hostnames", []) or []
    for h in hostnames:
        name = (h or {}).get("name", "")
        if name:
            hostname = name
            break

    if not hostname:
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror, OSError):
            pass

    # Phase 1.5: enrich vendor with our OUI table when nmap couldn't tell us
    vendor = enrich_vendor(mac, vendor)

    device_type = classify_device(hostname, vendor)

    return {
        "ip": ip,
        "mac": mac,
        "hostname": hostname,
        "vendor": vendor,
        "device_type": device_type,
        "status": "online",
    }
