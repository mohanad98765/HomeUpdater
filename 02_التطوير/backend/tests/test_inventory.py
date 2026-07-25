"""Installed-software inventory: the ``winget list`` parser + its endpoints.

The app previously knew only what was OUT OF DATE (``software_packages`` holds
packages that have an upgrade available). This is the other half: what is
actually installed, with a version — the input precise CVE matching needs.

The parser must survive an Arabic console (winget localizes headers) and rows
that carry NO Available column, which is the normal case for ``winget list`` and
exactly what the older upgrade-parser rejected.
"""

from __future__ import annotations

import pytest

from app.services import software_updates as sw

CSRF = {"X-HomeUpdater": "1"}

# Real-shaped English output: note row 1 has no Available, row 2 has one, and
# the last row has neither Available nor Source.
_EN = """
Name                 Id                     Version      Available  Source
------------------------------------------------------------------------------
7-Zip 23.01 (x64)    7zip.7zip              23.01                   winget
Mozilla Firefox      Mozilla.Firefox        130.0        131.0      winget
Local Tool           {A1B2C3D4-0000-0000}   4.5
"""

# Arabic Windows: headers localized, dashes separator identical, footer localized.
_AR = """
الاسم                المعرف                  الإصدار      متوفر      المصدر
------------------------------------------------------------------------------
Google Chrome        Google.Chrome          128.0.6613   129.0.6668  winget
مشغل الوسائط         Microsoft.Media        1.2.3                   winget

تتوفر ترقية لحزمة واحدة.
"""


def test_parses_rows_without_an_available_column():
    items = sw.parse_winget_list(_EN)
    by_id = {i.product_id: i for i in items}
    assert set(by_id) == {"7zip.7zip", "Mozilla.Firefox", "{A1B2C3D4-0000-0000}"}
    # The upgrade parser would have dropped this row (no Available value).
    assert by_id["7zip.7zip"].version == "23.01"
    assert by_id["7zip.7zip"].name == "7-Zip 23.01 (x64)"
    assert by_id["7zip.7zip"].source == "winget"


def test_available_column_is_not_mistaken_for_the_version():
    items = {i.product_id: i for i in sw.parse_winget_list(_EN)}
    # Version 130.0 is INSTALLED; 131.0 is merely available and must not be stored.
    assert items["Mozilla.Firefox"].version == "130.0"


def test_row_without_source_still_parses():
    items = {i.product_id: i for i in sw.parse_winget_list(_EN)}
    assert items["{A1B2C3D4-0000-0000}"].version == "4.5"
    assert items["{A1B2C3D4-0000-0000}"].name == "Local Tool"


def test_arabic_console_output_is_parsed_and_header_footer_rejected():
    items = sw.parse_winget_list(_AR)
    ids = {i.product_id for i in items}
    assert ids == {"Google.Chrome", "Microsoft.Media"}, "Arabic header/footer leaked in"
    by_id = {i.product_id: i for i in items}
    assert by_id["Google.Chrome"].version == "128.0.6613"  # not the 129 available
    assert by_id["Microsoft.Media"].name == "مشغل الوسائط"


def test_duplicate_product_ids_are_collapsed():
    text = """
Name        Id            Version   Source
-------------------------------------------
App x86     Vendor.App    1.0       winget
App x64     Vendor.App    1.0       winget
"""
    items = sw.parse_winget_list(text)
    assert len(items) == 1, "installed_software is one row per (device, product)"
    assert items[0].name == "App x86"  # first occurrence wins


def test_real_row_where_name_collides_with_id():
    """VERBATIM from real `winget list` output on a live machine: the Name column
    overflowed, so only ONE space separates it from the Id and both land in the
    same field. The first parser silently dropped VCRedist — a product whose
    version genuinely matters for vulnerability matching."""
    text = (
        "Name    Id    Version\n"
        "----------------------------------------\n"
        "Microsoft Visual C++ v14 Redistributable (x64) - 14.51.36247 "
        "Microsoft.VCRedist.2015+.x64                     14.51.36247.0\n"
    )
    items = sw.parse_winget_list(text)
    assert len(items) == 1, "collided Name/Id row must still be recovered"
    assert items[0].product_id == "Microsoft.VCRedist.2015+.x64"
    assert items[0].version == "14.51.36247.0"
    assert "Visual C++" in items[0].name


def test_real_row_with_spaces_inside_a_path_style_id():
    """Also verbatim from real output: an ARP-style Id legitimately contains
    spaces, so requiring a space-free Id dropped Microsoft 365 entirely."""
    text = (
        "Name    Id    Version\n"
        "----------------------------------------\n"
        "Microsoft 365 - ar-sa        ARP\\Machine\\X64\\O365HomePremRetail - ar-sa"
        "        16.0.20131.20154\n"
    )
    items = sw.parse_winget_list(text)
    assert len(items) == 1
    assert items[0].product_id == "ARP\\Machine\\X64\\O365HomePremRetail - ar-sa"
    assert items[0].version == "16.0.20131.20154"


def test_version_token_is_never_mistaken_for_an_id_during_repair():
    """The repair must not fire on a name ending in a version-looking token —
    an Id needs a letter plus a dot/backslash."""
    text = "Name    Version\n" "-------------------\n" "Some App 1.2.3     4.5.6\n"
    assert sw.parse_winget_list(text) == []


def test_empty_and_garbage_input_is_safe():
    assert sw.parse_winget_list("") == []
    assert sw.parse_winget_list("no table here\njust prose\n") == []


# --- endpoints ---------------------------------------------------------------
def test_inventory_starts_empty(client):
    r = client.get("/api/updates/inventory")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "last_seen": None}


def test_refresh_stores_inventory_then_lists_it(client, monkeypatch):
    async def fake_list():
        return (
            [
                sw.InstalledSoftwareInfo("Mozilla.Firefox", "Mozilla Firefox", "131.0"),
                sw.InstalledSoftwareInfo("7zip.7zip", "7-Zip", "23.01"),
            ],
            False,
        )

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2
    assert r.json()["new"] == 2
    assert r.json()["degraded"] is False

    listed = client.get("/api/updates/inventory").json()
    assert listed["total"] == 2
    assert {i["product_id"] for i in listed["items"]} == {"Mozilla.Firefox", "7zip.7zip"}
    assert all(i["device_id"] == 0 for i in listed["items"])  # hub rows


def test_refresh_updates_version_and_prunes_removed(client, monkeypatch):
    first = [
        sw.InstalledSoftwareInfo("Mozilla.Firefox", "Mozilla Firefox", "130.0"),
        sw.InstalledSoftwareInfo("Gone.App", "Gone", "1.0"),
    ]
    second = [sw.InstalledSoftwareInfo("Mozilla.Firefox", "Mozilla Firefox", "131.0")]

    async def run_first():
        return first, False

    async def run_second():
        return second, False

    monkeypatch.setattr("app.routers.updates.list_installed_software", run_first)
    client.post("/api/updates/inventory/refresh", headers=CSRF)
    monkeypatch.setattr("app.routers.updates.list_installed_software", run_second)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF).json()

    assert r["removed"] == 1, "an uninstalled product must leave the inventory"
    items = client.get("/api/updates/inventory").json()["items"]
    assert len(items) == 1
    assert items[0]["version"] == "131.0", "version must be refreshed in place"


def test_degraded_run_never_prunes(client, monkeypatch):
    """A non-zero winget exit can mean PARTIAL output. Deleting rows merely absent
    from it would silently destroy real inventory, so pruning is skipped."""

    async def full():
        return (
            [
                sw.InstalledSoftwareInfo("A.One", "One", "1.0"),
                sw.InstalledSoftwareInfo("B.Two", "Two", "2.0"),
            ],
            False,
        )

    async def partial_degraded():
        return [sw.InstalledSoftwareInfo("A.One", "One", "1.0")], True

    monkeypatch.setattr("app.routers.updates.list_installed_software", full)
    client.post("/api/updates/inventory/refresh", headers=CSRF)
    monkeypatch.setattr("app.routers.updates.list_installed_software", partial_degraded)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF).json()

    assert r["degraded"] is True
    assert r["removed"] == 0
    assert client.get("/api/updates/inventory").json()["total"] == 2, "B.Two was wrongly pruned"


def test_refresh_surfaces_winget_failure(client, monkeypatch):
    async def boom():
        raise sw.SoftwareUpdateError("winget not found")

    monkeypatch.setattr("app.routers.updates.list_installed_software", boom)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF)
    assert r.status_code == 500
    assert "winget not found" in r.text


def test_list_installed_software_refuses_non_windows(monkeypatch):
    """Guarded before any subprocess spawn — winget doesn't exist off Windows."""
    import asyncio

    monkeypatch.setattr(sw.sys, "platform", "linux")
    with pytest.raises(sw.SoftwareUpdateError, match="only available on Windows"):
        asyncio.run(sw.list_installed_software())
