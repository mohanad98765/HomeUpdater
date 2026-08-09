"""
Regression tests for the IEEE-verified OUI table.

The table was previously hand-guessed and ~35% of entries named the wrong
manufacturer (or a MAC prefix that IEEE never assigned). Every entry is now
verified against the official MA-L registry. These tests lock in the specific
corrections and the structural invariants so bad data can't creep back.
"""

from __future__ import annotations

import gzip
import json

import pytest

from app.services import mac_vendor
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


# --- the full IEEE registry -----------------------------------------------------------
# The curated table above is 287 prefixes. Measured on the first real network it faced,
# it named 0 of 15 manufacturers — every device showed as "unknown" with no name, which
# an owner reads as "the app did not find my devices". These tests cover the bundled
# registry that fixes that, and the two ways it could quietly stop working: the data file
# missing from the build, and a randomized address being blamed on a missing table.
def test_the_registry_ships_and_is_the_real_thing():
    path = mac_vendor._registry_path()
    assert path.is_file(), f"the OUI data file is missing from the build: {path}"
    assert mac_vendor.registry_size() > 30_000, "a truncated registry is worse than none"


def test_it_names_the_devices_that_were_unnamed_before():
    """Real prefixes from the network where the curated table scored zero."""
    measured = {
        "40:CB:C0:BE:74:27": "Apple",
        "9C:B8:B4:C5:A1:98": "AMPAK",
        "00:0A:84:30:02:02": "Rainsun",
        "28:32:C5:99:90:DB": "HUMAX",
        "A0:B3:39:06:18:DC": "Intel",
    }
    for mac, expected in measured.items():
        got = mac_vendor.lookup(mac)
        assert expected.lower() in got.lower(), f"{mac} -> {got!r}, expected ~{expected}"


def test_the_curated_name_wins_over_the_registry():
    """The registry's legal names are long; the curated ones were chosen for a human
    reading a list. A conflict must not silently swap 'Apple' for its registered form."""
    for prefix, curated in list(mac_vendor._OUI_DB.items())[:50]:
        assert mac_vendor.lookup(prefix + "112233") == curated


def test_a_randomized_address_is_not_a_missing_entry():
    """Android 10+ and iOS 14+ invent a per-network address by default. It is in no
    registry and never will be — so this must not be read as a gap in the table."""
    assert mac_vendor.is_randomized("8E:70:F8:11:22:33")
    assert mac_vendor.is_randomized("9E:D3:4C:11:22:33")
    assert mac_vendor.lookup("8E:70:F8:11:22:33") == ""
    assert not mac_vendor.is_randomized("40:CB:C0:BE:74:27")
    assert not mac_vendor.is_randomized("A4:AA:FE:D3:BC:4F")


def test_a_missing_registry_degrades_instead_of_breaking_the_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_vendor, "_REGISTRY", None)
    monkeypatch.setattr(mac_vendor, "_registry_path", lambda: tmp_path / "absent.json.gz")
    assert mac_vendor.registry_size() == 0
    assert mac_vendor.lookup("002608") == "Apple"  # the curated table still answers
    assert mac_vendor.lookup("40:CB:C0:BE:74:27") == ""
    monkeypatch.setattr(mac_vendor, "_REGISTRY", None)


def test_a_corrupt_registry_is_survived_too(monkeypatch, tmp_path):
    bad = tmp_path / "oui.json.gz"
    bad.write_bytes(gzip.compress(b"{not json"))
    monkeypatch.setattr(mac_vendor, "_REGISTRY", None)
    monkeypatch.setattr(mac_vendor, "_registry_path", lambda: bad)
    assert mac_vendor.registry_size() == 0
    monkeypatch.setattr(mac_vendor, "_REGISTRY", None)


def test_no_subdivided_block_is_attributed_to_one_company():
    """A block held by 'IEEE Registration Authority' is split across MA-M/MA-S owners, so
    naming it after anyone is a guess. The generator drops those; this proves it did."""
    with gzip.open(mac_vendor._registry_path(), "rt", encoding="utf-8") as fh:
        table = json.load(fh)
    offenders = [p for p, v in table.items() if "registration authority" in v.lower()]
    assert offenders == []
    assert all(len(p) == 6 for p in table), "MA-L prefixes only — six hex digits"


@pytest.mark.parametrize("mac", ["", "not-a-mac", "AA:BB", "GG:HH:II:JJ:KK:LL"])
def test_junk_input_still_returns_empty(mac):
    assert mac_vendor.lookup(mac) == ""
    assert mac_vendor.is_randomized(mac) is False
