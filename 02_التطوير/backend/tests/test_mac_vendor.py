"""
Regression tests for the IEEE-verified OUI table.

The table was previously hand-guessed and ~35% of entries named the wrong
manufacturer (or a MAC prefix that IEEE never assigned). Every entry is now
verified against the official MA-L registry. These tests lock in the specific
corrections and the structural invariants so bad data can't creep back.
"""

from __future__ import annotations

from app.services.mac_vendor import _OUI_DB, enrich_vendor, lookup

# Prefixes that used to name the wrong vendor -> their true IEEE holder.
CORRECTED = {
    "0026E2": "LG Electronics",  # was ASUS
    "0021CC": "Flextronics",  # was Intel
    "1C1B0D": "Gigabyte",  # was Intel
    "182032": "Apple",  # was Samsung
    "187C81": "Valeo",  # was Xiaomi
    "5091E3": "TP-Link",  # was Xiaomi
}

# Prefixes that were already correct and must stay put.
UNCHANGED = {
    "002608": "Apple",
    "00248C": "ASUS",
}

# Prefixes the original table invented -- absent from the IEEE registry, or a
# subdivided (MA-M/MA-S) block with no single owner. Must resolve to "".
REMOVED = ["8842F7", "504B70", "B0BE7B", "8C84A1", "F4C4D2", "DC4427"]


def test_corrected_prefixes_resolve_to_true_vendor():
    for prefix, vendor in CORRECTED.items():
        assert lookup(prefix) == vendor, prefix


def test_previously_correct_prefixes_are_unchanged():
    for prefix, vendor in UNCHANGED.items():
        assert lookup(prefix) == vendor, prefix


def test_unverifiable_prefixes_are_gone():
    for prefix in REMOVED:
        assert lookup(prefix) == "", prefix


def test_lookup_accepts_common_mac_formats():
    for mac in ("50:91:E3:11:22:33", "50-91-e3-11-22-33", "5091e3112233"):
        assert lookup(mac) == "TP-Link"


def test_lookup_unknown_and_malformed_return_empty():
    assert lookup("") == ""
    assert lookup("ZZ") == ""
    assert lookup("FF:FF:FF:00:00:00") == ""


def test_enrich_keeps_existing_vendor():
    assert enrich_vendor("5091E3112233", "nmap says TP-LINK") == "nmap says TP-LINK"
    assert enrich_vendor("5091E3112233", "") == "TP-Link"


def test_table_entries_are_well_formed():
    for key, value in _OUI_DB.items():
        assert len(key) == 6, key
        assert key == key.upper(), key
        assert all(c in "0123456789ABCDEF" for c in key), key
        assert value and value == value.strip(), key
