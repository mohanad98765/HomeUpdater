"""Devices scan:
  - the scan now runs in the BACKGROUND (POST returns {started} immediately),
  - the _persist_scan upsert handles the ARP quirks (MAC-less hosts coexist,
    two IPs sharing one MAC collapse to one row),
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


def test_duplicate_mac_in_one_scan_collapses():
    dev = {"hostname": "", "vendor": "", "device_type": "unknown"}
    devices = [
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.5", **dev},
        {"mac": "AA:BB:CC:00:00:01", "ip": "10.0.0.6", **dev},
    ]
    new_count, rows = asyncio.run(_persist(devices))
    assert new_count == 1  # deduped by MAC
    assert len(rows) == 1


def _noop_task(coro):
    coro.close()  # don't actually launch a real network scan in the test
    return None


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
