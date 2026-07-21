"""v1.4.5 critical reliability cluster: advisor concurrency guard, background
apply releasing the slot, and the pre-migration DB backup."""

from __future__ import annotations

import asyncio

import pytest

from app.db import _backup_db
from app.routers import advisor as advisor_router
from app.services import advisor
from app.services.update_progress import update_progress


def test_advisor_rejects_concurrent_call_when_busy(monkeypatch):
    monkeypatch.setattr(advisor, "get_api_key", lambda: "sk-ant-test-key")

    async def go():
        await advisor._advisor_lock.acquire()  # simulate an in-flight advisor call
        try:
            with pytest.raises(advisor.AdvisorError, match="busy|مشغول"):
                await advisor.analyze(None, lang_hint="en")  # db unused before the busy check
        finally:
            advisor._advisor_lock.release()

    asyncio.run(go())


def test_apply_background_releases_the_update_slot(monkeypatch):
    async def fake_apply(_db, _actions):
        return {"applied": 1}

    monkeypatch.setattr(advisor_router.advisor, "apply_plan", fake_apply)
    update_progress.is_running = False
    try:
        assert update_progress.try_claim("install")
        result = asyncio.run(advisor_router._run_apply_bg([{"type": "app", "id": "X"}]))
        assert result == {"applied": 1}
        assert update_progress.is_running is False  # slot released by the bg task
    finally:
        update_progress.is_running = False


def test_apply_background_releases_slot_even_on_failure(monkeypatch):
    async def boom(_db, _actions):
        raise RuntimeError("install blew up")

    monkeypatch.setattr(advisor_router.advisor, "apply_plan", boom)
    update_progress.is_running = False
    try:
        assert update_progress.try_claim("install")
        with pytest.raises(RuntimeError):
            asyncio.run(advisor_router._run_apply_bg([{"type": "app", "id": "X"}]))
        assert update_progress.is_running is False  # released on the error path too
    finally:
        update_progress.is_running = False


def test_db_backup_creates_snapshot_and_caps_to_three(tmp_path):
    dbf = tmp_path / "homeupdater.db"
    dbf.write_bytes(b"SQLite format 3\x00 not really but non-empty")
    for _ in range(5):
        _backup_db(f"sqlite:///{dbf.as_posix()}")
    backups = list(tmp_path.glob("homeupdater.db.bak-*"))
    assert 1 <= len(backups) <= 3  # snapshots kept, capped at 3


def test_db_backup_noops_for_memory_and_missing():
    _backup_db("sqlite://")  # in-memory — must not raise
    _backup_db("sqlite:///Z:/does/not/exist.db")  # missing file — must not raise
