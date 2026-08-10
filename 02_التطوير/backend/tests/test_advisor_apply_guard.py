"""The advisor's "Apply the plan" button, and the only thing that makes it safe.

An LLM proposes the plan and a button executes it. The guard is that every id is checked
against what is genuinely PENDING on this machine before anything runs — so the worst a
wrong or manipulated plan can do is nothing.

That guard had never been exercised. The manual checklist calls this "the most dangerous
button in the program" and says to stop and report if it fails; but it needs a funded API
key to reach, and the guard itself does not — it is a database check. These tests reach
it directly, so the safety property no longer depends on a paid round trip nobody has
made yet.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.orm import Base, SoftwarePackageORM, WindowsUpdateORM
from app.services import advisor


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _seed(db) -> None:
    db.add(
        SoftwarePackageORM(
            device_id=0,
            package_id="Mozilla.Firefox",
            name="Firefox",
            current_version="100.0",
            available_version="128.0",
            is_installed=False,  # pending
        )
    )
    db.add(
        SoftwarePackageORM(
            device_id=0,
            package_id="7zip.7zip",
            name="7-Zip",
            current_version="24.09",
            available_version="24.09",
            is_installed=True,  # already done — must NOT be re-installed
        )
    )
    db.add(
        WindowsUpdateORM(
            device_id=0, kind="windows", update_id="KB-PENDING", title="p", is_installed=False
        )
    )
    db.add(
        WindowsUpdateORM(
            device_id=0, kind="windows", update_id="KB-DONE", title="d", is_installed=True
        )
    )


def _run(actions, monkeypatch):
    """Apply a plan with every real installer replaced by a recorder."""
    called = {"apps": [], "windows": []}

    async def fake_install_many(ids):
        called["apps"].extend(ids)
        return {"installed": len(ids), "requested": len(ids)}

    async def fake_install_updates(ids):
        called["windows"].extend(ids)
        return {"installed": len(ids), "requested": len(ids), "reboot_required": False}

    monkeypatch.setattr("app.services.software_updates.install_many", fake_install_many)
    monkeypatch.setattr("app.services.windows_updates.install_updates", fake_install_updates)

    async def run():
        engine, Session = await _session()
        async with Session() as db:
            _seed(db)
            await db.commit()
            result = await advisor.apply_plan(db, actions)
        await engine.dispose()
        return result

    return asyncio.run(run()), called


def test_an_id_the_machine_never_reported_is_never_installed(monkeypatch):
    """The failure this guard exists to prevent: the model naming a package that is not
    pending — hallucinated, or suggested by something it read — and the button running it."""
    _result, called = _run(
        [
            {"type": "app", "id": "Evil.Backdoor"},
            {"type": "windows", "id": "KB-INVENTED"},
        ],
        monkeypatch,
    )
    assert called["apps"] == [], "an unknown package must not reach the installer"
    assert called["windows"] == [], "an unknown update must not reach the installer"


def test_something_already_installed_is_not_installed_again(monkeypatch):
    _result, called = _run(
        [{"type": "app", "id": "7zip.7zip"}, {"type": "windows", "id": "KB-DONE"}],
        monkeypatch,
    )
    assert called["apps"] == [] and called["windows"] == []


def test_a_genuinely_pending_update_does_run(monkeypatch):
    """The guard must not be a wall: a plan naming real pending work has to work, or the
    feature is theatre."""
    _result, called = _run(
        [{"type": "app", "id": "Mozilla.Firefox"}, {"type": "windows", "id": "KB-PENDING"}],
        monkeypatch,
    )
    assert called["apps"] == ["Mozilla.Firefox"]
    assert called["windows"] == ["KB-PENDING"]


def test_one_bad_id_does_not_carry_the_good_ones_with_it(monkeypatch):
    """Nor does it let them through: the valid half runs, the invented half does not."""
    _result, called = _run(
        [
            {"type": "app", "id": "Mozilla.Firefox"},
            {"type": "app", "id": "Evil.Backdoor"},
            {"type": "windows", "id": "KB-PENDING"},
            {"type": "windows", "id": "KB-INVENTED"},
        ],
        monkeypatch,
    )
    assert called["apps"] == ["Mozilla.Firefox"]
    assert called["windows"] == ["KB-PENDING"]


def test_an_unknown_action_type_is_ignored(monkeypatch):
    _result, called = _run(
        [{"type": "run_command", "id": "format C:"}, {"type": "shell", "id": "curl evil"}],
        monkeypatch,
    )
    assert called["apps"] == [] and called["windows"] == []
