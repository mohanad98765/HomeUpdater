"""Devices scan:
  - the scan now runs in the BACKGROUND (POST returns {started} immediately),
  - the _persist_scan upsert handles the ARP quirks (MAC-less hosts coexist;
    several IPs sharing ONE MAC are devices reached through a router, and must each
    keep their own row instead of collapsing into the router's),
  - a concurrent scan is rejected with 409.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.orm import Base, DeviceORM
from app.routers.devices import _persist_scan
from app.services.progress import scan_progress
from tests.conftest import CSRF_HEADER


async def _persist(devices: list[dict]) -> tuple[int, list[tuple]]:
    """Run _persist_scan against a fresh in-memory DB; return (new_count, rows)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,  # one shared connection so create_all + session see the same DB
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        new_count = await _persist_scan(
            db, {"subnet": "10.0.0.0/24", "devices": devices}, datetime.now(UTC)
        )
        rows = (await db.execute(select(DeviceORM))).scalars().all()
        out = [(r.ip, r.mac, r.device_type) for r in rows]
    await engine.dispose()
    return new_count, out


def test_two_macless_devices_coexist():
    devices = [
        {"mac": "", "ip": "10.0.0.2", "hostname": "", "vendor": "", "device_type": "unknown"},
        {
            "mac": "",
            "ip": "10.0.0.3",
            "hostname": "h3",
            "vendor": "Dell",
            "device_type": "computer",
        },
        {
            "mac": "AA:BB:CC:DD:EE:FF",
            "ip": "10.0.0.1",
            "hostname": "r",
            "vendor": "TP-Link",
            "device_type": "router",
        },
    ]
    new_count, rows = asyncio.run(_persist(devices))
    assert new_count == 3
    assert len([r for r in rows if r[1] is None]) == 2  # both MAC-less coexist (mac=NULL)


def test_addresses_behind_one_mac_are_separate_devices(monkeypatch):
    """This test previously asserted the opposite, and that is the whole story.

    A router answers ARP for everything it routes to, so on any network with more than
    one segment EVERY off-link device carries the gateway's MAC. Collapsing by MAC then
    turned a whole segment into a single row: the devices are on the network, the app
    probed them, and the list showed one entry. Measured on the CEO's own LAN, where
    192.168.3.1 and 192.168.100.5 both answer with A4:AA:FE:D3:BC:4F and the database
    held exactly one row for the pair.
    """
    monkeypatch.setattr("app.routers.devices.get_network_info", lambda: None)
    dev = {"hostname": "", "vendor": "", "device_type": "unknown"}
    devices = [
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.5", **dev},
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.6", **dev},
    ]
    new_count, rows = asyncio.run(_persist(devices))
    assert new_count == 2, "two addresses answered; two devices exist"
    assert sorted(r[0] for r in rows) == ["10.0.0.5", "10.0.0.6"]
    # The MAC identifies exactly one of them — the lowest address here, since no
    # gateway is known. The other is honestly recorded as MAC-less: ARP never told us
    # its hardware address, it only told us the router's.
    assert sorted((r[0], r[1]) for r in rows) == [
        ("10.0.0.5", "AA:BB:CC:00:00:01"),
        ("10.0.0.6", None),
    ]


def test_the_gateway_keeps_the_mac_when_we_know_which_one_it_is(monkeypatch):
    class _Info:
        gateway_ip = "10.0.0.1"

    monkeypatch.setattr("app.routers.devices.get_network_info", lambda: _Info())
    dev = {"hostname": "", "vendor": "", "device_type": "unknown"}
    devices = [
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.9", **dev},
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.1", **dev},
    ]
    new_count, rows = asyncio.run(_persist(devices))
    assert new_count == 2
    assert dict((r[0], r[1]) for r in rows) == {
        "10.0.0.1": "AA:BB:CC:00:00:01",  # the router owns its own MAC
        "10.0.0.9": None,  # reached through it
    }


def test_a_mac_seen_once_still_identifies_its_device(monkeypatch):
    """The change must not weaken normal identity: on a flat network every device has
    its own MAC, and a MAC seen at exactly one address still identifies its device and
    is stored on the row. (Re-identification across scans lives in
    tests/test_devices_mac_migration.py.)"""
    monkeypatch.setattr("app.routers.devices.get_network_info", lambda: None)
    dev = {"hostname": "", "vendor": "", "device_type": "unknown"}
    first = [{"mac": "AA:BB:CC:00:00:07", "ip": "10.0.0.7", **dev}]
    new_count, rows = asyncio.run(_persist(first))
    assert (new_count, len(rows)) == (1, 1)
    assert rows[0][1] == "AA:BB:CC:00:00:07"


class _StubTask:
    """Stand-in for the asyncio.Task so trigger_scan can add_done_callback/track it."""

    def add_done_callback(self, _cb):
        pass


def _noop_task(coro):
    coro.close()  # don't actually launch a real network scan in the test
    return _StubTask()


def test_scan_starts_in_background(client, monkeypatch):
    scan_progress.is_running = False
    monkeypatch.setattr("app.routers.devices.asyncio.create_task", _noop_task)
    try:
        r = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["started"] is True
        assert "subnet" in body
        assert scan_progress.is_running is True  # marked running synchronously
    finally:
        scan_progress.is_running = False


def test_concurrent_scan_rejected(client):
    scan_progress.is_running = True
    try:
        r = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER)
        assert r.status_code == 409
    finally:
        scan_progress.is_running = False
