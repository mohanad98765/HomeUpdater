"""Per-device scoping of updates/packages + the installed_software inventory.

Before this, ``software_packages.package_id`` and ``windows_updates.update_id``
were GLOBALLY unique, so two machines on different versions of the same package
could not coexist — a fleet was not representable at all. These tests pin the new
contract so a future "cleanup" can't quietly restore global uniqueness.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import _run_migrations
from app.models.orm import (
    HUB_DEVICE_ID,
    Base,
    InstalledSoftwareORM,
    SoftwarePackageORM,
    WindowsUpdateORM,
)


@pytest.fixture
def session(tmp_path):
    """An isolated session against the ORM-created schema."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'scope.db').as_posix()}", poolclass=NullPool
    )
    asyncio.run(_create(engine))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield maker
    asyncio.run(engine.dispose())


async def _create(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_hub_is_device_zero():
    assert HUB_DEVICE_ID == 0


def test_same_package_can_exist_on_two_devices(session):
    """The whole point: one package_id, two machines, two versions."""

    async def run():
        async with session() as db:
            db.add_all(
                [
                    SoftwarePackageORM(
                        device_id=HUB_DEVICE_ID, package_id="Google.Chrome", current_version="120"
                    ),
                    SoftwarePackageORM(
                        device_id=7, package_id="Google.Chrome", current_version="118"
                    ),
                ]
            )
            await db.commit()
            rows = (
                (
                    await db.execute(
                        select(SoftwarePackageORM).where(
                            SoftwarePackageORM.package_id == "Google.Chrome"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {r.device_id for r in rows} == {0, 7}
            assert {r.current_version for r in rows} == {"120", "118"}

    asyncio.run(run())


def test_same_package_twice_on_one_device_is_rejected(session):
    """Uniqueness still holds WITHIN a device — including the hub (device 0).
    A nullable FK would have failed this, since NULLs are distinct in a UNIQUE
    index; that is exactly why the hub uses a 0 sentinel."""

    async def run():
        async with session() as db:
            db.add(SoftwarePackageORM(device_id=HUB_DEVICE_ID, package_id="7zip.7zip"))
            await db.commit()
            db.add(SoftwarePackageORM(device_id=HUB_DEVICE_ID, package_id="7zip.7zip"))
            with pytest.raises(IntegrityError):
                await db.commit()

    asyncio.run(run())


def test_same_update_id_across_devices_and_kinds(session):
    async def run():
        async with session() as db:
            db.add_all(
                [
                    WindowsUpdateORM(device_id=0, kind="windows", update_id="u-1"),
                    WindowsUpdateORM(device_id=3, kind="windows", update_id="u-1"),
                    WindowsUpdateORM(device_id=0, kind="driver", update_id="u-1"),
                ]
            )
            await db.commit()
            rows = (await db.execute(select(WindowsUpdateORM))).scalars().all()
            assert len(rows) == 3

    asyncio.run(run())


def test_installed_software_records_version_per_device(session):
    """The inventory answers 'what IS installed' — the missing half that CPE
    matching needs (product AND version)."""

    async def run():
        async with session() as db:
            db.add_all(
                [
                    InstalledSoftwareORM(
                        device_id=0,
                        product_id="Mozilla.Firefox",
                        name="Firefox",
                        version="131.0",
                        publisher="Mozilla",
                    ),
                    InstalledSoftwareORM(
                        device_id=5, product_id="Mozilla.Firefox", name="Firefox", version="126.0"
                    ),
                ]
            )
            await db.commit()
            rows = (await db.execute(select(InstalledSoftwareORM))).scalars().all()
            assert {(r.device_id, r.version) for r in rows} == {(0, "131.0"), (5, "126.0")}
            # cpe stays empty until step 3 lands — asserted so nobody assumes it's populated
            assert all(r.cpe == "" for r in rows)
            assert rows[0].to_dict()["publisher"] == "Mozilla"

    asyncio.run(run())


def test_duplicate_product_on_same_device_is_rejected(session):
    async def run():
        async with session() as db:
            db.add(InstalledSoftwareORM(device_id=0, product_id="Notepad++.Notepad++"))
            await db.commit()
            db.add(InstalledSoftwareORM(device_id=0, product_id="Notepad++.Notepad++"))
            with pytest.raises(IntegrityError):
                await db.commit()

    asyncio.run(run())


# --- the real Alembic path, not just metadata.create_all --------------------
def test_migration_adds_device_scope_and_inventory(tmp_path, monkeypatch):
    db = tmp_path / "migrated.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db.as_posix()}")

    _run_migrations()

    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert "installed_software" in tables

    for table in ("software_packages", "windows_updates"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "device_id" in cols, f"{table} must be device-scoped"

    # The composite UNIQUE indexes must exist, and the old global ones must not.
    def unique_indexes(table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA index_list({table})") if r[2]}

    assert "uq_software_packages_device_package" in unique_indexes("software_packages")
    assert "ix_software_packages_package_id" not in unique_indexes("software_packages")
    assert "uq_windows_updates_device_kind_update" in unique_indexes("windows_updates")
    assert "ix_windows_updates_update_id" not in unique_indexes("windows_updates")
    assert "uq_installed_software_device_product" in unique_indexes("installed_software")
