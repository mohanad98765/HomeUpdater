"""
Lightweight device-type classifier based on vendor + hostname heuristics.

This is intentionally simple. In Phase 2 we will refine it using
mDNS service hints (zeroconf) and SNMP probes. For now we just want a
reasonable type label so the frontend can show the right icon.

Returns one of: "router", "phone", "computer", "smart_tv", "iot", "unknown".
"""

from __future__ import annotations


# ---- Vendor / hostname keyword tables (lower-cased) ---------------

_ROUTER_VENDORS = (
    "tp-link", "tplink", "asus", "netgear", "d-link", "dlink", "cisco",
    "huawei technologies", "linksys", "mikrotik", "ubiquiti", "tenda",
    "zte", "fritz", "avm", "aruba", "ruckus", "draytek", "openwrt",
)
_ROUTER_HOSTNAMES = (
    "router", "gateway", "modem", "wifi", "ap-",
)

_PHONE_VENDORS = (
    "samsung electronics", "huawei device", "xiaomi", "oppo", "vivo",
    "oneplus", "realme", "honor", "nokia mobile", "google mobile",
    "motorola mobility",
)
_PHONE_HOSTNAMES = (
    "iphone", "ipad", "android", "phone", "galaxy", "redmi",
    "mi-phone", "huawei-p", "pixel",
)

_TV_VENDORS = (
    "lg electronics", "lg innotek", "sony interactive", "vizio",
    "tcl king", "hisense", "philips consumer", "samsung display",
)
_TV_HOSTNAMES = (
    "tv", "smarttv", "roku", "chromecast", "firetv", "apple-tv",
    "bravia", "shield",
)

_IOT_VENDORS = (
    "espressif", "tuya", "shenzhen", "broadlink", "amazon technologies",
    "google nest", "philips hue", "ring", "arlo", "wyze", "ezviz",
)
_IOT_HOSTNAMES = (
    "echo", "alexa", "nest", "hue", "smartplug", "camera", "doorbell",
)

_COMPUTER_VENDORS = (
    "intel corporate", "intel(r)", "dell inc", "hewlett packard",
    "lenovo", "microsoft corporation", "asustek", "asus computer",
    "msi", "razer", "framework",
)


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


def classify_device(
    *,
    vendor: str = "",
    hostname: str = "",
    ip: str = "",
    gateway_ip: str | None = None,
) -> str:
    """Return device type label. Keep behavior conservative."""
    v = (vendor or "").lower().strip()
    h = (hostname or "").lower().strip()

    # 1) Gateway IP is always router
    if gateway_ip and ip == gateway_ip:
        return "router"

    # 2) Router signals
    if _has_kw(v, _ROUTER_VENDORS) or _has_kw(h, _ROUTER_HOSTNAMES):
        return "router"

    # 3) Phone signals (vendor first because it's stronger)
    if _has_kw(v, _PHONE_VENDORS) or _has_kw(h, _PHONE_HOSTNAMES):
        return "phone"

    # 4) Apple — disambiguate via hostname
    if "apple" in v:
        if any(k in h for k in ("iphone", "ipad", "ipod")):
            return "phone"
        if any(k in h for k in ("apple-tv", "appletv")):
            return "smart_tv"
        return "computer"

    # 5) Smart TVs
    if _has_kw(v, _TV_VENDORS) or _has_kw(h, _TV_HOSTNAMES):
        return "smart_tv"

    # 6) IoT
    if _has_kw(v, _IOT_VENDORS) or _has_kw(h, _IOT_HOSTNAMES):
        return "iot"

    # 7) Computers
    if _has_kw(v, _COMPUTER_VENDORS):
        return "computer"

    return "unknown"
