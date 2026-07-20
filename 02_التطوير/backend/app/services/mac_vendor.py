"""
MAC OUI -> vendor lookup.

We bundle a hand-curated list of common manufacturer prefixes covering the
most likely devices on a home network (routers, phones, computers, smart
TVs, IoT). For any MAC outside the list, returns "" -- discovery.py will
keep nmap's own vendor string when available.

Every prefix below is a 24-bit MA-L assignment verified against the official
IEEE OUI registry (https://standards-oui.ieee.org/oui/oui.csv). Vendor names
are normalized to a short, human-readable form of the registered holder.

The full IEEE OUI registry has ~40 000 prefixes (~3.8 MB). For a home tool
the curated list below is enough to identify most consumer devices. If we
ever want full coverage, we can fetch and cache oui.csv on first run. That
stays as a future enhancement.
"""

from __future__ import annotations

# Maps the first 3 octets (uppercase, no separators, e.g. "5C5F67") to a
# manufacturer name. Covers the most common consumer device makers.
# Verified against the IEEE OUI registry; see module docstring.
_OUI_DB: dict[str, str] = {
    # ---- Apple ---------------------------------------------------------
    "001451": "Apple",
    "0017F2": "Apple",
    "001E52": "Apple",
    "0023DF": "Apple",
    "00254B": "Apple",
    "002608": "Apple",
    "0026B0": "Apple",
    "0026BB": "Apple",
    "041552": "Apple",
    "087045": "Apple",
    "0CBC9F": "Apple",
    "0CD746": "Apple",
    "1093E9": "Apple",
    "182032": "Apple",
    "28E14C": "Apple",
    "30F7C5": "Apple",
    "34159E": "Apple",
    "404D7F": "Apple",
    "4C8D79": "Apple",
    "5855CA": "Apple",
    "5C95AE": "Apple",
    "6C4008": "Apple",
    "70CD60": "Apple",
    "78A3E4": "Apple",
    "7C6D62": "Apple",
    "84FCAC": "Apple",
    "8C2937": "Apple",
    "9027E4": "Apple",
    "98F0AB": "Apple",
    "A4B197": "Apple",
    "A8667F": "Apple",
    "AC3C0B": "Apple",
    "B065BD": "Apple",
    "B8C75D": "Apple",
    "BC52B7": "Apple",
    "C82A14": "Apple",
    "CC25EF": "Apple",
    "D02598": "Apple",
    "D89E3F": "Apple",
    "DC2B61": "Apple",
    "E0F847": "Apple",
    "E80688": "Apple",
    "F0DBE2": "Apple",
    "F4F15A": "Apple",
    "FCD848": "Apple",
    # ---- Samsung Electronics -------------------------------------------
    "001599": "Samsung Electronics",
    "001E7D": "Samsung Electronics",
    "002566": "Samsung Electronics",
    "30CDA7": "Samsung Electronics",
    "38AA3C": "Samsung Electronics",
    "3C5A37": "Samsung Electronics",
    "5440AD": "Samsung Electronics",
    "5C0A5B": "Samsung Electronics",
    "606BBD": "Samsung Electronics",
    "84A466": "Samsung Electronics",
    "94350A": "Samsung Electronics",
    "AC5F3E": "Samsung Electronics",
    "C81479": "Samsung Electronics",
    "D487D8": "Samsung Electronics",
    "E8B4C8": "Samsung Electronics",
    "F0728C": "Samsung Electronics",
    # ---- Xiaomi --------------------------------------------------------
    "286C07": "Xiaomi",
    "742344": "Xiaomi",
    "8CBEBE": "Xiaomi",
    "98FAE3": "Xiaomi",
    "A086C6": "Xiaomi",
    "B0E235": "Xiaomi",
    "C40BCB": "Xiaomi",
    "C46AB7": "Xiaomi",
    "F0B429": "Xiaomi",
    # ---- Huawei Technologies -------------------------------------------
    "001882": "Huawei Technologies",
    "002568": "Huawei Technologies",
    "00259E": "Huawei Technologies",
    "00464B": "Huawei Technologies",
    "10C61F": "Huawei Technologies",
    "1C1D67": "Huawei Technologies",
    "20A680": "Huawei Technologies",
    "346BD3": "Huawei Technologies",
    "60DE44": "Huawei Technologies",
    "84A8E4": "Huawei Technologies",
    "9CB2B2": "Huawei Technologies",
    "AC4E91": "Huawei Technologies",
    "D03E5C": "Huawei Technologies",
    "F4559C": "Huawei Technologies",
    # ---- TP-Link -------------------------------------------------------
    "001D0F": "TP-Link",
    "1027F5": "TP-Link",
    "14CC20": "TP-Link",
    "18A6F7": "TP-Link",
    "30B5C2": "TP-Link",
    "3C46D8": "TP-Link",
    "5091E3": "TP-Link",
    "60E327": "TP-Link",
    "AC84C6": "TP-Link",
    "B0BE76": "TP-Link",
    "C006C3": "TP-Link",
    "E848B8": "TP-Link",
    # ---- ASUS ----------------------------------------------------------
    "001E8C": "ASUS",
    "001FC6": "ASUS",
    "002354": "ASUS",
    "00248C": "ASUS",
    "08606E": "ASUS",
    "1C872C": "ASUS",
    "2C56DC": "ASUS",
    "305A3A": "ASUS",
    "50465D": "ASUS",
    "5404A6": "ASUS",
    "AC9E17": "ASUS",
    "BCEE7B": "ASUS",
    "D45D64": "ASUS",
    "F46D04": "ASUS",
    # ---- Netgear -------------------------------------------------------
    "00146C": "Netgear",
    "001E2A": "Netgear",
    "0024B2": "Netgear",
    "0026F2": "Netgear",
    "10DA43": "Netgear",
    "20E52A": "Netgear",
    "2CB05D": "Netgear",
    "44A56E": "Netgear",
    "6CB0CE": "Netgear",
    "78D294": "Netgear",
    "841B5E": "Netgear",
    "9C3DCF": "Netgear",
    "A040A0": "Netgear",
    "C03F0E": "Netgear",
    "C40415": "Netgear",
    # ---- D-Link --------------------------------------------------------
    "001195": "D-Link",
    "00179A": "D-Link",
    "001CF0": "D-Link",
    "001E58": "D-Link",
    "1CAFF7": "D-Link",
    "5CD998": "D-Link",
    "BCF685": "D-Link",
    # ---- Cisco-Linksys -------------------------------------------------
    "001839": "Cisco-Linksys",
    "001D7E": "Cisco-Linksys",
    "002369": "Cisco-Linksys",
    # ---- Cisco ---------------------------------------------------------
    "001D45": "Cisco",
    "0026CB": "Cisco",
    "08D09F": "Cisco",
    "2C0BE9": "Cisco",
    "F84F57": "Cisco",
    # ---- Intel Corporate -----------------------------------------------
    "001B21": "Intel Corporate",
    "001E64": "Intel Corporate",
    "0CD292": "Intel Corporate",
    "34F39A": "Intel Corporate",
    "5CE0C5": "Intel Corporate",
    "7C7635": "Intel Corporate",
    "8086F2": "Intel Corporate",
    "94B86D": "Intel Corporate",
    "AC2B6E": "Intel Corporate",
    "AC7BA1": "Intel Corporate",
    "D43B04": "Intel Corporate",
    "DC215C": "Intel Corporate",
    # ---- Microsoft Corporation -----------------------------------------
    "00125A": "Microsoft Corporation",
    "0017FA": "Microsoft Corporation",
    "0050F2": "Microsoft Corporation",
    "7C1E52": "Microsoft Corporation",
    "F01DBC": "Microsoft Corporation",
    # ---- Dell Inc ------------------------------------------------------
    "001C23": "Dell Inc",
    "0024E8": "Dell Inc",
    "002564": "Dell Inc",
    "0026B9": "Dell Inc",
    "246E96": "Dell Inc",
    "30D042": "Dell Inc",
    "5C260A": "Dell Inc",
    "B083FE": "Dell Inc",
    "B8AC6F": "Dell Inc",
    "C03EBA": "Dell Inc",
    "D4BED9": "Dell Inc",
    "F8B156": "Dell Inc",
    # ---- HP Inc --------------------------------------------------------
    "0014C2": "HP Inc",
    "001A4B": "HP Inc",
    "001CC4": "HP Inc",
    "001F29": "HP Inc",
    "1062E5": "HP Inc",
    "30E171": "HP Inc",
    "40A8F0": "HP Inc",
    "8CDCD4": "HP Inc",
    "9C8E99": "HP Inc",
    "B05ADA": "HP Inc",
    "B499BA": "HP Inc",
    "C4346B": "HP Inc",
    "C8CBB8": "HP Inc",
    "E4E749": "HP Inc",
    "EC9A74": "HP Inc",
    # ---- Lenovo --------------------------------------------------------
    "10C595": "Lenovo",
    "48C35A": "Lenovo",
    "74042B": "Lenovo",
    "A03299": "Lenovo",
    "A41194": "Lenovo",
    "C8DDC9": "Lenovo",
    # ---- Acer ----------------------------------------------------------
    "000124": "Acer",
    "C09879": "Acer",
    # ---- MSI -----------------------------------------------------------
    "0019DB": "MSI",
    "002185": "MSI",
    "002421": "MSI",
    "448A5B": "MSI",
    "D43D7E": "MSI",
    "D8CB8A": "MSI",
    # ---- LG Electronics ------------------------------------------------
    "001E75": "LG Electronics",
    "001F6B": "LG Electronics",
    "0026E2": "LG Electronics",
    "C4366C": "LG Electronics",
    "F80CF3": "LG Electronics",
    # ---- Sony Corporation ----------------------------------------------
    "001A80": "Sony Corporation",
    "001DBA": "Sony Corporation",
    "0024BE": "Sony Corporation",
    "30F9ED": "Sony Corporation",
    "AC9B0A": "Sony Corporation",
    # ---- Vizio ---------------------------------------------------------
    "006B9E": "Vizio",
    "3C9BD6": "Vizio",
    "A06A44": "Vizio",
    "A48D3B": "Vizio",
    "C41CFF": "Vizio",
    "CC95D7": "Vizio",
    # ---- TCL -----------------------------------------------------------
    "08C3B3": "TCL",
    "0C718C": "TCL",
    "3C591E": "TCL",
    "408BF6": "TCL",
    "B4695F": "TCL",
    "C07982": "TCL",
    # ---- Hisense -------------------------------------------------------
    "20BEB4": "Hisense",
    "90CF7D": "Hisense",
    "A88200": "Hisense",
    "A8A648": "Hisense",
    "B84DEE": "Hisense",
    "E43BC9": "Hisense",
    # ---- Roku ----------------------------------------------------------
    "B0A737": "Roku",
    "B83E59": "Roku",
    "CC6DA0": "Roku",
    # ---- Google --------------------------------------------------------
    "94EB2C": "Google",
    "F4F5D8": "Google",
    # ---- Amazon Technologies -------------------------------------------
    "10AE60": "Amazon Technologies",
    "44650D": "Amazon Technologies",
    "74C246": "Amazon Technologies",
    "AC63BE": "Amazon Technologies",
    "B47C9C": "Amazon Technologies",
    "F0272D": "Amazon Technologies",
    "F0D2F1": "Amazon Technologies",
    "FC65DE": "Amazon Technologies",
    # ---- Espressif -----------------------------------------------------
    "10521C": "Espressif",
    "246F28": "Espressif",
    "30AEA4": "Espressif",
    "3C71BF": "Espressif",
    "807D3A": "Espressif",
    "84F3EB": "Espressif",
    "8CAAB5": "Espressif",
    "A4CF12": "Espressif",
    "C45BBE": "Espressif",
    "C8C9A3": "Espressif",
    "EC94CB": "Espressif",
    # ---- Philips (Signify) ---------------------------------------------
    "001788": "Philips (Signify)",
    # ---- Raspberry Pi --------------------------------------------------
    "2CCF67": "Raspberry Pi",
    "B827EB": "Raspberry Pi",
    "DCA632": "Raspberry Pi",
    "E45F01": "Raspberry Pi",
    # ---- Other IEEE-verified vendors (ODMs, module makers, phone brands) ---
    "08FBEA": "AMPAK",
    "0026B6": "Askey",
    "240A64": "AzureWave",
    "5C9656": "AzureWave",
    "002106": "BlackBerry (RIM)",
    "0040F4": "CAMEO Communications",
    "A0CEC8": "CE Link",
    "1C7508": "Compal",
    "5C0E8B": "Extreme Networks",
    "B0E2E5": "FiberHome",
    "0021CC": "Flextronics",
    "1C1B0D": "Gigabyte",
    "F0F249": "Hitron",
    "342387": "Hon Hai (Foxconn)",
    "642737": "Hon Hai (Foxconn)",
    "C85B76": "LCFC",
    "3C9509": "Liteon",
    "20DF3F": "Nanjing SAC Power Grid",
    "2C5BB8": "OPPO",
    "E840F2": "Pegatron",
    "002472": "ReDriven Power",
    "0023A7": "Redpine Signals",
    "00264C": "Shanghai DigiVision",
    "F0DEB9": "Shanghai Y&Y Electronics",
    "94E36D": "Texas Instruments",
    "001E76": "Thermo Fisher Scientific",
    "DC9FDB": "Ubiquiti",
    "001A6B": "Universal Global Scientific (USI)",
    "187C81": "Valeo",
    "08B7EC": "Wireless Seismic",
    "B0CE18": "Zhejiang Shenghui Lighting",
    "684A76": "eero",
}


def _normalize(mac: str) -> str:
    """Strip separators, uppercase. Returns "" if input is too short."""
    cleaned = "".join(c for c in (mac or "") if c.isalnum()).upper()
    return cleaned if len(cleaned) >= 6 else ""


def lookup(mac: str) -> str:
    """
    Return the manufacturer name for the given MAC, or "" if unknown.
    Accepts any common MAC format (AA:BB:CC..., AA-BB-CC..., AABBCC...).
    """
    norm = _normalize(mac)
    if not norm:
        return ""
    return _OUI_DB.get(norm[:6], "")


def enrich_vendor(mac: str, current: str) -> str:
    """
    Return the best-known vendor name. If `current` is non-empty, keep it
    (nmap's lookup is usually richer). Otherwise, try our OUI table.
    """
    if current and current.strip():
        return current
    return lookup(mac)
