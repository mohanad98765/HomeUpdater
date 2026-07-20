"""
Pure-Python host discovery — no nmap, no Npcap, no admin rights.

Sends a lightweight TCP-connect probe to every address in the subnet, which
makes the OS resolve each reachable host at layer 2 (ARP), then reads the OS
ARP cache via ``arp -a`` for IP -> MAC. Reverse-DNS and the OUI table enrich
each device. This is the discovery path the shipped installer uses, because
bundling nmap/Npcap is license-restricted.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from .mac_vendor import enrich_vendor
from .network_utils import classify_device, get_network_info, normalize_mac
from .progress import scan_progress

MAX_SWEEP_HOSTS = 1024
PROBE_CONCURRENCY = 256
PROBE_PORT = 80
# 1.2s (was 0.4s): a phone in Wi-Fi power-save only wakes its radio at DTIM
# intervals, so it misses a 0.4s single-shot window but answers within ~1.2s +
# a second pass. This is the main reason phones dropped out of the pure-Python
# scan vs. nmap (which retries with a ~1.5s RTT timeout).
PROBE_TIMEOUT = 1.2

# Dedicated pool for reverse-DNS: gethostbyaddr threads for PTR-less hosts run
# the full ~3s and can't be cancelled, so they must NOT share the default
# executor with the WUA/winget/ADB blocking calls (which also use
# run_in_executor(None, ...)) or a scan would stall those operations.
_RDNS_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="rdns")


def _hosts_to_sweep(target: str) -> tuple[list[str], str]:
    """Host list for the sweep, capped so a /16 or /8 doesn't mean millions of
    probes. The size is checked BEFORE materializing the list, otherwise a /8
    would build ~16M strings."""
    net = ipaddress.IPv4Network(target, strict=False)
    if net.num_addresses - 2 <= MAX_SWEEP_HOSTS:
        return [str(h) for h in net.hosts()], ""

    info = get_network_info()
    if info and info.local_ip:
        small = ipaddress.IPv4Network(f"{info.local_ip}/24", strict=False)
        return [str(h) for h in small.hosts()], f"شبكة كبيرة — قصر المسح على {small}"

    capped: list[str] = []
    for host in net.hosts():
        capped.append(str(host))
        if len(capped) >= MAX_SWEEP_HOSTS:
            break
    return capped, f"شبكة كبيرة — قصر المسح على أول {MAX_SWEEP_HOSTS} عنوان"


async def _probe(ip: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, PROBE_PORT), timeout=PROBE_TIMEOUT
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            # Any outcome is fine — sending the SYN already populated the ARP cache.
            pass


async def _sweep(hosts: list[str]) -> None:
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)
    tasks = [asyncio.create_task(_probe(h, sem)) for h in hosts]
    done = 0
    for fut in asyncio.as_completed(tasks):
        await fut
        done += 1
        if done % 64 == 0 or done == len(hosts):
            scan_progress.add("scanning", f"جسّ {done}/{len(hosts)} عنواناً")


def parse_arp_table(output: str) -> dict[str, str]:
    """Parse ``arp -a`` output into {ip: MAC}, skipping broadcast/multicast rows."""
    table: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, raw_mac = parts[0], parts[1]
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        mac = normalize_mac(raw_mac)
        if not mac or mac in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
            continue
        if mac.startswith(("01:00:5E", "33:33")):  # IPv4 / IPv6 multicast
            continue
        if ip.endswith(".255") or ip.split(".")[0] in ("224", "239", "255"):
            continue
        table[ip] = mac
    return table


def _read_arp_table() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["arp", "-a"],
            stdin=subprocess.DEVNULL,  # windowed builds have no valid stdin handle
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as exc:
        logger.warning(f"arp -a failed: {exc}")
        return {}
    return parse_arp_table(result.stdout)


def _resolve(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return ""


def _ip_sort_key(ip: str) -> tuple:
    try:
        return tuple(int(p) for p in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)


def _local_device() -> dict[str, Any] | None:
    """The scanning machine itself — it is never in its own ARP cache."""
    info = get_network_info()
    if not info or not info.local_ip:
        return None
    mac = ""
    try:
        import psutil

        for _name, addrs in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address == info.local_ip for a in addrs):
                for a in addrs:
                    if a.family == psutil.AF_LINK and a.address:
                        mac = normalize_mac(a.address)
                        break
                break
    except Exception:
        pass
    vendor = enrich_vendor(mac, "")
    return {
        "ip": info.local_ip,
        "mac": mac,
        "hostname": socket.gethostname(),
        "vendor": vendor,
        "device_type": "computer",
        "status": "online",
    }


async def discover_python(target: str) -> list[dict[str, Any]]:
    """Discover live hosts on ``target`` without nmap. Updates scan_progress."""
    hosts, note = _hosts_to_sweep(target)
    if note:
        scan_progress.set_phase("scanning", note)
    scan_progress.set_phase("scanning", f"مسح {len(hosts)} عنواناً (Python: TCP + ARP، بلا nmap)")
    await _sweep(hosts)
    arp = _read_arp_table()

    # Second pass over hosts that didn't answer the first (short) window —
    # power-saving phones frequently miss the first probe and reply to a retry.
    missing = [h for h in hosts if h not in arp]
    if missing:
        scan_progress.set_phase(
            "scanning", f"تمريرة ثانية لـ {len(missing)} عنواناً لم يردّ (أجهزة قد تكون نائمة)"
        )
        await _sweep(missing)
        arp = {**arp, **_read_arp_table()}

    scan_progress.set_phase("resolving", "قراءة جدول ARP وحلّ الأسماء")

    loop = asyncio.get_event_loop()
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()

    local = _local_device()
    if local:
        devices.append(local)
        seen.add(local["ip"])
        scan_progress.update_count(len(devices), f"هذا الجهاز {local['ip']}")

    targets = [(ip, arp[ip]) for ip in sorted(arp, key=_ip_sort_key) if ip not in seen]
    scan_progress.set_phase("resolving", f"حلّ أسماء {len(targets)} جهازاً")

    async def _resolve_async(ip: str) -> str:
        # Reverse-DNS in parallel with a per-host cap, so hosts without a PTR
        # record don't serialize into a multi-minute wait.
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_RDNS_EXECUTOR, _resolve, ip), timeout=3.0
            )
        except Exception:
            return ""

    hostnames = await asyncio.gather(*(_resolve_async(ip) for ip, _ in targets))

    for (ip, mac), hostname in zip(targets, hostnames, strict=True):
        vendor = enrich_vendor(mac, "")
        devices.append(
            {
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "vendor": vendor,
                "device_type": classify_device(hostname, vendor),
                "status": "online",
            }
        )
        suffix = f"({vendor})" if vendor else ""
        scan_progress.update_count(len(devices), f"وُجد {ip} {suffix}".strip())

    return devices
