"""Tests for the background scan scheduler (T7). See app/services/scheduler.py.

Contract: the scheduler stays OFF unless opted in, never spawns a duplicate
loop, cleans up on stop, floors the interval at 5 minutes, and survives a
failing tick (one bad scan must not kill the loop).

Notes for maintainers:
- ``_task`` is a module global, so we reset ``scheduler._task`` via the module
  (importing the value would only bind a stale copy).
- ``start_scan`` / ``get_local_subnet`` are imported LAZILY inside ``_loop``,
  so they are patched at their SOURCE modules, not on ``scheduler``.
- Async is driven with ``asyncio.run`` to match the rest of the suite.
"""

import asyncio

import pytest

import app.services.scheduler as sched


@pytest.fixture(autouse=True)
def _reset_task():
    """Isolate the module-global _task between tests."""
    sched._task = None
    yield
    if sched._task is not None and not sched._task.done():
        sched._task.cancel()
    sched._task = None


def test_start_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(sched.settings, "scan_scheduler_enabled", False)
    sched.start()
    assert sched._task is None


def test_start_creates_task_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(sched.settings, "scan_scheduler_enabled", True)

    async def run():
        sched.start()
        first = sched._task
        assert first is not None
        sched.start()  # a second start with a live task must NOT replace it
        assert sched._task is first
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return first

    task = asyncio.run(run())
    assert task.cancelled()


def test_stop_cancels_and_clears(monkeypatch):
    monkeypatch.setattr(sched.settings, "scan_scheduler_enabled", True)

    async def run():
        sched.start()
        task = sched._task
        sched.stop()
        assert sched._task is None  # cleared immediately
        with pytest.raises(asyncio.CancelledError):
            await task  # the cancellation actually lands

    asyncio.run(run())


def test_interval_is_floored_at_five_minutes(monkeypatch):
    # 1 minute is below the 5-minute floor -> max(5, 1) * 60 == 300s.
    monkeypatch.setattr(sched.settings, "scan_interval_minutes", 1)
    monkeypatch.setattr("app.services.network_utils.get_local_subnet", lambda: None)

    sleeps: list[int] = []

    async def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 2:  # startup settle + first interval seen -> stop
            raise asyncio.CancelledError

    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sched._loop()

    asyncio.run(run())
    assert sleeps[0] == 120  # startup settle = min(interval, 120)
    assert 300 in sleeps  # the floored interval, not 60


def test_failing_tick_does_not_kill_loop(monkeypatch):
    monkeypatch.setattr(sched.settings, "scan_scheduler_enabled", True)
    monkeypatch.setattr(sched.settings, "scan_interval_minutes", 30)

    calls = {"n": 0}

    def flaky_subnet():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")  # first tick blows up
        return None  # later ticks: no subnet -> scan skipped

    monkeypatch.setattr("app.services.network_utils.get_local_subnet", flaky_subnet)
    monkeypatch.setattr("app.routers.devices.start_scan", lambda target: False)

    n_sleeps = {"n": 0}

    async def fake_sleep(secs):
        n_sleeps["n"] += 1
        if n_sleeps["n"] >= 3:  # startup + two loop iterations
            raise asyncio.CancelledError

    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sched._loop()

    asyncio.run(run())
    # The loop swallowed the first tick's RuntimeError and reached a second tick.
    assert calls["n"] >= 2
