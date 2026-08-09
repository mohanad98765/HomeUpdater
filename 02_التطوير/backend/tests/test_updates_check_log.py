"""The "last checked" line must be a fact about the check, not about the newest row.

Before this, a check that found nothing wrote nothing, so pressing the button and being
told "not checked yet" was the app's honest reading of its own data — on a tab with no
rows, forever. Zero results is an answer and now has somewhere to live.

Also covers the version pulled out of a Windows Update title: on the owner's machine 14
stored updates were all the same KB with the same visible title, and the version was the
only thing that distinguished them — sitting at the end of a 118-character string, which
is exactly the part a truncated table cell removes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.orm import Base, WindowsUpdateORM, title_version
from app.routers.updates import _last_check, _list_wua_updates, _record_check


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def test_a_check_that_finds_nothing_is_still_a_check():
    async def run():
        engine, Session = await _session()
        async with Session() as db:
            before = await _list_wua_updates(db, "driver")
            assert before["last_checked"] is None
            assert before["last_check_found"] is None, "never checked"

            now = datetime.now(UTC)
            await _record_check(db, "driver", 0, now)
            await db.commit()

            after = await _list_wua_updates(db, "driver")
            assert after["last_checked"] is not None, "the button was pressed; say so"
            assert after["last_check_found"] == 0, "checked, and there was genuinely nothing"
        await engine.dispose()

    asyncio.run(run())


def test_the_stamp_survives_and_is_replaced_not_duplicated():
    async def run():
        engine, Session = await _session()
        async with Session() as db:
            first = datetime(2026, 8, 1, tzinfo=UTC)
            second = datetime(2026, 8, 9, tzinfo=UTC)
            await _record_check(db, "windows", 3, first)
            await db.commit()
            await _record_check(db, "windows", 0, second)
            await db.commit()
            row = await _last_check(db, "windows")
            assert row.checked_at.replace(tzinfo=UTC) == second
            assert row.found == 0
        await engine.dispose()

    asyncio.run(run())


def test_kinds_do_not_share_a_timestamp():
    async def run():
        engine, Session = await _session()
        async with Session() as db:
            await _record_check(db, "windows", 2, datetime(2026, 8, 9, tzinfo=UTC))
            await db.commit()
            drivers = await _list_wua_updates(db, "driver")
            assert drivers["last_checked"] is None, "checking Windows is not checking drivers"
        await engine.dispose()

    asyncio.run(run())


def test_an_installed_row_no_longer_freezes_the_header():
    """The old header was the newest row's timestamp, so it could sit at a date whose
    updates were long since installed."""

    async def run():
        engine, Session = await _session()
        async with Session() as db:
            db.add(
                WindowsUpdateORM(
                    device_id=0,
                    kind="windows",
                    update_id="old",
                    title="something (1.2.3.4)",
                    is_installed=True,
                    last_checked=datetime(2026, 7, 1, tzinfo=UTC),
                )
            )
            await db.commit()
            listed = await _list_wua_updates(db, "windows")
            assert listed["last_checked"] is None, "a stored row is not a record of a check"
        await engine.dispose()

    asyncio.run(run())


# --- the field that tells two identical-looking updates apart ------------------------
def test_the_version_is_pulled_out_of_the_title():
    real = (
        "تحديث معلومات الأمان Microsoft Defender Antivirus -2267602 قاعدة المعارف "
        "(الإصدار 1.457.77.0) - القناة الحالية (موسعة)"
    )
    assert title_version(real) == "1.457.77.0"


def test_two_updates_that_look_identical_are_distinguished():
    a = "تحديث ... (الإصدار 1.457.69.0) - القناة الحالية"
    b = "تحديث ... (الإصدار 1.457.77.0) - القناة الحالية"
    assert a[:20] == b[:20], "the visible part really is identical"
    assert title_version(a) != title_version(b)


def test_a_title_without_a_version_returns_empty_not_a_guess():
    assert title_version("2026-07 Cumulative Update for Windows 11") == ""
    assert title_version("") == ""
    assert title_version("KB5001234") == ""
