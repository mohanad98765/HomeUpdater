"""
Tests for the updates router:
  - empty cached lists have the right shape
  - a check/install is rejected with 409 while another operation is running
"""

from __future__ import annotations

import asyncio
import threading
import time

from app.services import windows_updates as wu
from app.services.adaptive_timeout import DurationCeiling
from app.services.update_progress import update_progress
from tests.conftest import CSRF_HEADER


def test_windows_list_empty(client):
    r = client.get("/api/updates/windows")
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] == []
    assert body["total_pending"] == 0


def test_software_list_empty(client):
    r = client.get("/api/updates/software")
    assert r.status_code == 200
    assert r.json()["total_pending"] == 0


def test_windows_check_rejected_while_busy(client):
    update_progress.is_running = True
    try:
        r = client.post("/api/updates/windows/check", json={}, headers=CSRF_HEADER)
        assert r.status_code == 409
    finally:
        update_progress.is_running = False


def test_software_check_rejected_while_busy(client):
    update_progress.is_running = True
    try:
        r = client.post("/api/updates/software/check", json={}, headers=CSRF_HEADER)
        assert r.status_code == 409
    finally:
        update_progress.is_running = False


def test_try_claim_is_atomic_and_releasable():
    # The slot can be claimed once; a second claim fails until released. This is
    # what closes the check-then-act race on the "install all" await gap.
    update_progress.is_running = False
    try:
        assert update_progress.try_claim("install") is True
        assert update_progress.try_claim("check") is False  # already held
        update_progress.release()
        assert update_progress.try_claim("check") is True  # free again
    finally:
        update_progress.release()


def test_wua_run_bounded_aborts_a_hung_com_call():
    # A wedged WUA COM call used to hang the await forever and leave
    # update_progress.is_running set (409 on every later op). It must now be
    # bounded by the adaptive ceiling and surface an error instead.
    release = threading.Event()

    def hang(_arg):
        release.wait(5)  # simulates a stuck Search()/Install()
        return "late"

    ceiling = DurationCeiling(floor=0.1, ceiling=0.15, safety=1.0)

    async def go():
        t0 = time.monotonic()
        raised = False
        try:
            await wu._run_bounded(hang, "x", ceiling=ceiling, op="test search")
        except wu.WindowsUpdateError as exc:
            raised = True
            assert "abandoned" in str(exc)
        elapsed = time.monotonic() - t0
        release.set()  # let the orphan thread finish so loop teardown is quick
        return raised, elapsed

    raised, elapsed = asyncio.run(go())
    assert raised
    assert elapsed < 2.0  # bounded, not the full 5s hang


def test_wua_run_bounded_returns_and_learns_on_success():
    def quick(_arg):
        time.sleep(0.02)  # measurable above the OS monotonic-clock granularity
        return ["ok"]

    ceiling = DurationCeiling(floor=0.1, ceiling=5.0, safety=3.0)
    assert ceiling.ewma is None  # cold
    result = asyncio.run(wu._run_bounded(quick, "x", ceiling=ceiling, op="test"))
    assert result == ["ok"]
    assert ceiling.ewma is not None  # duration folded in for next time
