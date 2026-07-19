"""
Network utility helpers - subnet detection, gateway lookup, MAC normalization,
device classification.

Used by the discovery service.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
from dataclasses import asdict, dataclass

import psutil
from loguru import logger

# Maximum subnet size we will scan automatically. Anything broader than /24
# (i.e. prefix < 24) gets capped to /24 around the local IP, because:
#  * Home routers almost always use /24
#  * ARP broadcasts don't traverse routers, so /16 + /8 are mostly wasted
#  * Nmap of a /16 takes minutes and usually returns nothing useful
SAFE_PREFIX_LEN = 24


# ===================================================================
# 1) Subnet / Network info detection
# ===================================================================
@dataclass
class NetworkInfo:
    """Snapshot of the active local network."""

    local_ip: str
    netmask: str
    raw_subnet: str  # what Windows reports (could be huge, e.g. /16)
    suggested_subnet: str  # capped to /24 for fast scanning
    gateway_ip: str | None
    interface_name: str

    def to_dict(self) -> dict:
        return asdict(self)


def _outbound_ip() -> str | None:
    """Return the IP used to reach the public internet (no traffic sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError as exc:
        logger.warning(f"Could not detect outbound IP: {exc}")
        return None


def _get_default_gateway() -> str | None:
    """
    Read the default IPv4 gateway. Windows-only via `route print`.
    Returns None on Linux/Mac (we will fall back to "<network>.1" guess).
    """
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["route", "PRINT", "0.0.0.0"],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="ignore",
        )
        # Lines look like:
        #   0.0.0.0   0.0.0.0   192.168.1.1   192.168.1.42   10
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                candidate = parts[2]
                try:
                    ipaddress.IPv4Address(candidate)
                    return candidate
                except ValueError:
                    continue
    except Exception as exc:
        logger.warning(f"Could not read default gateway via route: {exc}")
    return None


def _cap_subnet(local_ip: str, network: ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    """If the detected network is larger than /24, narrow it to /24 around local_ip."""
    if network.prefixlen >= SAFE_PREFIX_LEN:
        return network
    try:
        return ipaddress.IPv4Network(f"{local_ip}/{SAFE_PREFIX_LEN}", strict=False)
    except ValueError:
        return network


def get_network_info() -> NetworkInfo | None:
    """Detect everything we know about the active local network."""
    local_ip = _outbound_ip()
    if not local_ip:
        return None

    iface_name = ""
    netmask = "255.255.255.0"
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and a.address == local_ip and a.netmask:
                iface_name = name
                netmask = a.netmask
                break
        if iface_name:
            break

    try:
        raw_net = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
    except ValueError:
        raw_net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)

    suggested_net = _cap_subnet(local_ip, raw_net)

    # Default gateway: try OS first, fall back to "<network>.1"
    gw = _get_default_gateway()
    if not gw:
        try:
            gw = str(next(suggested_net.hosts()))
        except StopIteration:
            gw = None

    return NetworkInfo(
        local_ip=local_ip,
        netmask=netmask,
        raw_subnet=str(raw_net),
        suggested_subnet=str(suggested_net),
        gateway_ip=gw,
        interface_name=iface_name,
    )


def get_local_subnet(default: str = "192.168.1.0/24") -> str:
    """
    Return the FULL local CIDR exactly as Windows reports it (honors the
    real netmask). The user explicitly asked for this on 2026-04-28: scanning
    according to the actual subnet mask is the correct behaviour.

    A separate `suggested_subnet` (/24 around local IP) is still exposed via
    /api/devices/info for users who want a quick fallback scan.
    """
    info = get_network_info()
    return info.raw_subnet if info else default


def list_local_interfaces() -> list[dict]:
    """Return a brief list of interfaces with their IPv4 addresses."""
    out = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith("127."):
                out.append({"name": name, "ip": a.address, "netmask": a.netmask or ""})
    return out


# ===================================================================
# 2) MAC normalization
# ===================================================================
def normalize_mac(mac: str) -> str:
    """Return MAC in canonical AA:BB:CC:DD:EE:FF form, or '' if invalid."""
    if not mac:
        return ""
    cleaned = "".join(c for c in mac if c.isalnum())
    if len(cleaned) != 12:
        return ""
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2)).upper()


# ===================================================================
# 3) Subnet validation (used by API layer)
# ===================================================================
def is_valid_cidr(value: str) -> bool:
    """Return True if value is a valid IPv4 CIDR (e.g. '192.168.1.0/24')."""
    if not value:
        return False
    try:
        ipaddress.IPv4Network(value.strip(), strict=False)
        return True
    except (ValueError, TypeError):
        return False


# ===================================================================
# 4) Device-type classifier (heuristic)
# ===================================================================
_ROUTER_VENDORS = (
    "cisco",
    "tp-link",
    "tplink",
    "asus",
    "asustek",
    "netgear",
    "mikrotik",
    "ubiquiti",
    "linksys",
    "d-link",
    "dlink",
    "huawei tech",
    "zte",
    "fortinet",
    "fritzbox",
    "avm",
    "mercusys",
)
_PHONE_VENDORS = (
    "apple",
    "samsung",
    "huawei device",
    "xiaomi",
    "oneplus",
    "oppo",
    "vivo",
    "realme",
    "honor",
    "motorola",
)
_TV_VENDORS = (
    "lg electronics",
    "sony",
    "tcl",
    "vizio",
    "roku",
    "hisense",
    "panasonic",
    "philips tv",
)
_COMPUTER_VENDORS = (
    "dell",
    "hp inc",
    "hewlett",
    "lenovo",
    "intel corp",
    "acer",
    "msi",
    "razer",
    "microsoft corp",
)
_IOT_VENDORS = (
    "ring",
    "amazon technologies",
    "google nest",
    "google llc",
    "ecobee",
    "tuya",
    "philips lighting",
    "espressif",
    "tplink iot",
    "shelly",
    "sonoff",
    "raspberrypi",
    "raspberry pi",
)


def classify_device(hostname: str, vendor: str) -> str:
    """Heuristic device-type guess. Returns one of:
    router | phone | computer | smart_tv | iot | unknown."""
    h = (hostname or "").lower()
    v = (vendor or "").lower()

    if any(k in v for k in _ROUTER_VENDORS):
        return "router"
    if any(k in h for k in ("router", "gateway", "modem", "openwrt")):
        return "router"

    if any(k in v for k in _TV_VENDORS):
        return "smart_tv"
    if any(k in h for k in ("tv", "appletv", "chromecast", "firetv", "nvidia-shield")):
        return "smart_tv"

    if any(k in v for k in _PHONE_VENDORS):
        return "phone"
    if any(k in h for k in ("iphone", "ipad", "android", "galaxy", "redmi")):
        return "phone"

    if any(k in v for k in _COMPUTER_VENDORS):
        return "computer"
    if any(k in h for k in ("desktop", "laptop", "pc-", "-pc")):
        return "computer"

    if any(k in v for k in _IOT_VENDORS):
        return "iot"

    return "unknown"
