"""
Network info helpers — subnet detection, default gateway, local IP.

These helpers do not depend on nmap; they use stdlib + psutil.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional

import psutil


@dataclass
class NetworkInfo:
    """Information about the active local network."""

    local_ip: str
    netmask: str
    subnet_cidr: str  # e.g. "192.168.1.0/24"
    gateway_ip: Optional[str]
    interface_name: str


def _get_outbound_ip() -> Optional[str]:
    """Return the IP used to reach the public internet (no traffic sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # No actual packet is sent — the socket library just picks an interface.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _find_iface_for_ip(ip: str) -> Optional[tuple[str, str]]:
    """Return (interface_name, netmask) for the interface holding the given IP."""
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address == ip:
                return iface, addr.netmask or "255.255.255.0"
    return None


def _guess_gateway(local_ip: str, netmask: str) -> Optional[str]:
    """Try psutil first; fallback to assuming x.x.x.1."""
    try:
        # psutil.net_if_stats / net_io_counters do not expose gateway.
        # net_connections might. But the simplest cross-platform fallback:
        # the gateway is almost always at <network>.1 on home networks.
        net = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
        # Yield first usable host
        return str(next(net.hosts()))
    except Exception:
        return None


def get_network_info() -> Optional[NetworkInfo]:
    """Detect the active local subnet for scanning."""
    local_ip = _get_outbound_ip()
    if not local_ip:
        return None

    iface_match = _find_iface_for_ip(local_ip)
    if not iface_match:
        return None
    iface_name, netmask = iface_match

    try:
        net = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
        subnet_cidr = str(net)
    except Exception:
        return None

    return NetworkInfo(
        local_ip=local_ip,
        netmask=netmask,
        subnet_cidr=subnet_cidr,
        gateway_ip=_guess_gateway(local_ip, netmask),
        interface_name=iface_name,
    )
