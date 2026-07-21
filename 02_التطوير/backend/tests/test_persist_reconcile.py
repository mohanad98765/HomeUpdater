"""Scan-persistence identity reconciliation (v1.4.4): a device must not lose its
user rename or spawn duplicates when its MAC resolves late, rotates, or its
classification momentarily drops to 'unknown'."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.orm import Base, DeviceORM
from app.routers.devices import _persist_scan


def _dev(mac, ip, hostname="", vendor="", device_type="unknown"):
    return {
        "mac": mac,
        "ip": ip,
        "hostname": hostname,
        "vendor": vendor,
        "device_type": device_type,
    }


def _scan(devices):
    return {"subnet": "10.0.0.0/24", "devices": devices}


def _run(scenario):
    async def go():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session() as db:
            out = await scenario(db)
        await engine.dispose()
        return out

    return asyncio.run(go())


def test_macless_then_mac_upgrades_in_place_keeping_name():
    async def scenario(db):
        now = datetime.now(UTC)
        await _persist_scan(db, _scan([_dev(None, "10.0.0.5", "tv", "", "smart_tv")]), now)
        row = (await db.execute(select(DeviceORM))).scalar_one()
        row.custom_name = "غرفة الجلوس"
        await db.commit()
        await _persist_scan(
            db, _scan([_dev("AA:BB:CC:00:00:01", "10.0.0.5", "tv", "Sony", "smart_tv")]), now
        )
        return list((await db.execute(select(DeviceORM))).scalars().all())

    rows = _run(scenario)
    assert len(rows) == 1  # upgraded in place, not duplicated
    assert rows[0].mac == "AA:BB:CC:00:00:01"  # MAC backfilled
    assert rows[0].custom_name == "غرفة الجلوس"  # rename preserved


def test_device_type_does_not_regress_to_unknown():
    async def scenario(db):
        now = datetime.now(UTC)
        mac = "AA:BB:CC:00:00:02"
        await _persist_scan(
            db, _scan([_dev(mac, "10.0.0.6", "living-room-tv", "Sony", "smart_tv")]), now
        )
        await _persist_scan(db, _scan([_dev(mac, "10.0.0.6", "", "", "unknown")]), now)
        return (await db.execute(select(DeviceORM))).scalar_one()

    row = _run(scenario)
    assert row.device_type == "smart_tv"  # not regressed to unknown
    assert row.hostname == "living-room-tv"  # last good hostname kept


def test_mac_rotation_carries_name_and_drops_duplicate():
    async def scenario(db):
        now = datetime.now(UTC)
        await _persist_scan(
            db, _scan([_dev("AA:BB:CC:00:00:03", "10.0.0.7", "phone", "Apple", "phone")]), now
        )
        row = (await db.execute(select(DeviceORM))).scalar_one()
        row.custom_name = "جوال أحمد"
        await db.commit()
        # private-MAC rotation: same IP + hostname, new MAC
        await _persist_scan(
            db, _scan([_dev("DD:EE:FF:00:00:99", "10.0.0.7", "phone", "Apple", "phone")]), now
        )
        return list((await db.execute(select(DeviceORM))).scalars().all())

    rows = _run(scenario)
    assert len(rows) == 1  # stale duplicate dropped
    assert rows[0].mac == "DD:EE:FF:00:00:99"  # live row is the new MAC
    assert rows[0].custom_name == "جوال أحمد"  # name carried over
    assert rows[0].is_online is True


def test_recycled_ip_on_a_different_macless_device_resets_metadata():
    async def scenario(db):
        now = datetime.now(UTC)
        await _persist_scan(db, _scan([_dev(None, "10.0.0.40", "printer", "HP", "printer")]), now)
        row = (await db.execute(select(DeviceORM))).scalar_one()
        row.custom_name = "طابعة المكتب"
        row.notes = "الحبر ينفد"
        await db.commit()
        # DHCP gives .40 to a different MAC-less device (distinct hostname)
        await _persist_scan(
            db, _scan([_dev(None, "10.0.0.40", "guest-laptop", "Dell", "computer")]), now
        )
        return (await db.execute(select(DeviceORM))).scalar_one()

    row = _run(scenario)
    assert row.hostname == "guest-laptop"
    assert row.custom_name == ""  # not mislabelled with the printer's name
    assert row.notes == ""
