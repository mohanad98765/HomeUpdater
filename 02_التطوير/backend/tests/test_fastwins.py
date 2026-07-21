"""Fast-wins backend features (v1.4.6): manageable flag (T15), update-check
version compare (T4), advisor consent state (T11), scheduler gate (T7)."""

from __future__ import annotations

import asyncio

from app.models.orm import DeviceORM
from app.routers.system import _ver_tuple
from app.services import scheduler


def test_manageable_flag_reflects_device_type():
    assert DeviceORM(ip="10.0.0.2", device_type="computer").to_dict()["manageable"] is True
    assert DeviceORM(ip="10.0.0.3", device_type="phone").to_dict()["manageable"] is True
    assert DeviceORM(ip="10.0.0.4", device_type="router").to_dict()["manageable"] is False
    assert DeviceORM(ip="10.0.0.5", device_type="smart_tv").to_dict()["manageable"] is False
    assert DeviceORM(ip="10.0.0.6", device_type="unknown").to_dict()["manageable"] is False


def test_ver_tuple_orders_versions():
    assert _ver_tuple("1.4.6") > _ver_tuple("1.4.5")
    assert _ver_tuple("1.4.10") > _ver_tuple("1.4.9")  # numeric, not lexical
    assert _ver_tuple("2.0.0") > _ver_tuple("1.9.9")
    assert not (_ver_tuple("1.4.5") > _ver_tuple("1.4.5"))
    assert _ver_tuple("1.4.5") == _ver_tuple("1.4.5")


def test_advisor_consent_roundtrip(tmp_path, monkeypatch):
    from app.services import advisor

    monkeypatch.setattr(advisor, "get_data_dir", lambda: tmp_path)
    assert advisor.has_consent() is False
    advisor.record_consent()
    assert advisor.has_consent() is True
    advisor.revoke_consent()
    assert advisor.has_consent() is False


def test_scheduler_is_gated_off_by_default(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "scan_scheduler_enabled", False)

    async def go():
        scheduler.stop()
        scheduler.start()
        return scheduler._task

    assert asyncio.run(go()) is None


def test_scheduler_starts_when_enabled(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "scan_scheduler_enabled", True)

    async def go():
        scheduler.stop()
        scheduler.start()
        task = scheduler._task
        scheduler.stop()  # cancel before the loop's first (long) sleep elapses
        return task

    task = asyncio.run(go())
    assert task is not None
