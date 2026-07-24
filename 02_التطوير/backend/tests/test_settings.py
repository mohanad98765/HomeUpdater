"""User-editable settings: GET/POST /api/system/settings + save_settings whitelist.

The in-app Settings page reads and writes scan_method / scan_scheduler_enabled /
scan_interval_minutes. Persistence goes to config.json under the isolated test
data dir; the live ``settings`` object is mutated in place. A strict whitelist
keeps a request from ever rewriting security-sensitive keys.
"""

from __future__ import annotations

import json

import pytest

from app.config import get_appdata_dir, save_settings, settings

CSRF = {"X-HomeUpdater": "1"}


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot + restore the mutable global settings and config.json so a test's
    writes never leak into the next."""
    snap = {
        "scan_method": settings.scan_method,
        "scan_scheduler_enabled": settings.scan_scheduler_enabled,
        "scan_interval_minutes": settings.scan_interval_minutes,
    }
    cfg = get_appdata_dir() / "config.json"
    prev = cfg.read_text(encoding="utf-8") if cfg.exists() else None
    try:
        yield
    finally:
        for k, v in snap.items():
            setattr(settings, k, v)
        if prev is None:
            if cfg.exists():
                cfg.unlink()
        else:
            cfg.write_text(prev, encoding="utf-8")


# --- unit: save_settings whitelist -----------------------------------------
def test_save_settings_applies_whitelisted_and_persists():
    applied = save_settings({"scan_method": "python", "scan_interval_minutes": 45})
    assert applied == {"scan_method": "python", "scan_interval_minutes": 45}
    assert settings.scan_method == "python"
    assert settings.scan_interval_minutes == 45
    on_disk = json.loads((get_appdata_dir() / "config.json").read_text(encoding="utf-8"))
    assert on_disk["scan_method"] == "python"
    assert on_disk["scan_interval_minutes"] == 45


def test_save_settings_ignores_non_whitelisted_keys():
    before = settings.database_url
    applied = save_settings({"database_url": "sqlite:///evil", "session_token": "x"})
    assert applied == {}
    assert settings.database_url == before  # untouched
    cfg = get_appdata_dir() / "config.json"
    if cfg.exists():  # a no-op must not persist the rejected keys
        assert "database_url" not in json.loads(cfg.read_text(encoding="utf-8"))


# --- endpoint ---------------------------------------------------------------
def test_get_settings_returns_the_three_keys(client):
    r = client.get("/api/system/settings")
    assert r.status_code == 200
    assert set(r.json()) == {"scan_method", "scan_scheduler_enabled", "scan_interval_minutes"}


def test_post_settings_persists_and_reflects(client):
    r = client.post("/api/system/settings", json={"scan_method": "nmap"}, headers=CSRF)
    assert r.status_code == 200
    assert r.json()["scan_method"] == "nmap"
    assert "scan_method" in r.json()["applied"]
    # A subsequent GET reflects the change (it was applied to the live settings).
    assert client.get("/api/system/settings").json()["scan_method"] == "nmap"


def test_post_settings_interval_out_of_range_422(client):
    low = client.post("/api/system/settings", json={"scan_interval_minutes": 3}, headers=CSRF)
    high = client.post("/api/system/settings", json={"scan_interval_minutes": 5000}, headers=CSRF)
    assert low.status_code == 422
    assert high.status_code == 422


def test_post_settings_bad_method_422(client):
    r = client.post("/api/system/settings", json={"scan_method": "bogus"}, headers=CSRF)
    assert r.status_code == 422


def test_toggle_scheduler_restarts_it(client, monkeypatch):
    """Flipping the scheduler flag must re-apply it (stop → start) so the change
    takes effect immediately, not on the next restart."""
    calls: list[str] = []
    from app.services import scheduler

    monkeypatch.setattr(scheduler, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(scheduler, "start", lambda: calls.append("start"))
    r = client.post("/api/system/settings", json={"scan_scheduler_enabled": True}, headers=CSRF)
    assert r.status_code == 200
    assert r.json()["scan_scheduler_enabled"] is True
    assert calls == ["stop", "start"]
