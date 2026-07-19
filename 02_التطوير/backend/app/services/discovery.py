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
from typing import Any

import nmap
from loguru import logger

from ..config import settings
from .discovery_python import discover_python
from .mac_vendor import enrich_vendor
from .network_utils import classify_device, get_local_subnet, normalize_mac
from .progress import scan_progress

# How long to give nmap to scan the whole subnet, end-to-end.
# Set high because /16 networks can take several minutes.
DEFAULT_SCAN_TIMEOUT_SECONDS = 600  # 10 minutes


class DiscoveryError(RuntimeError):
    """Raised when nmap fails to scan (e.g. nmap not installed, no admin)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _nmap_available() -> bool:
    return shutil.which("nmap") is not None


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
    scan_progress.begin(target)

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

    scan_progress.finish(len(devices))
    logger.info(f"Scan complete on {target}: {len(devices)} device(s) found")
    return {
        "subnet": target,
        "devices": devices,
        "host_count": len(devices),
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

    if host_estimate >= 1024:
        scan_progress.set_phase(
            "scanning",
            f"Probing {host_estimate:,} addresses with nmap (may take several minutes)",
        )
    elif host_estimate > 0:
        scan_progress.set_phase("scanning", f"Probing {host_estimate} addresses with nmap")
    else:
        scan_progress.set_phase("scanning", "Probing addresses with nmap")

    # Heartbeat — append a log line every 10s while nmap is running so the
    # UI shows continuous activity even when nmap itself is silent for minutes.
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
    try:
        devices: list[dict[str, Any]] = await loop.run_in_executor(None, _do_scan, target, timeout)
    finally:
        heartbeat_task.cancel()

    scan_progress.set_phase("classifying", "Classifying device types")
    return devices


# ---------------------------------------------------------------------------
# Internal — runs in executor (blocking)
# ---------------------------------------------------------------------------
def _do_scan(subnet: str, timeout: int) -> list[dict[str, Any]]:
    """Synchronous nmap scan. Called from a thread by ``scan_network``."""
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
        f"--min-parallelism 64 --min-hostgroup 64 --host-timeout {timeout}s"
    )
    try:
        nm.scan(hosts=subnet, arguments=args)
    except nmap.PortScannerError as e:
        logger.exception("nmap scan failed")
        raise DiscoveryError(f"nmap scan failed: {e}") from e

    devices: list[dict[str, Any]] = []
    all_hosts = nm.all_hosts()
    if all_hosts:
        scan_progress.set_phase(
            "resolving",
            f"Resolving hostnames for {len(all_hosts)} responding device(s)",
        )
    for ip in all_hosts:
        try:
            entry = _parse_host(nm, ip)
            if entry:
                devices.append(entry)
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
