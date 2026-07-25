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
def test_get_settings_returns_exactly_the_editable_surface(client):
    r = client.get("/api/system/settings")
    assert r.status_code == 200
    assert set(r.json()) == {
        "scan_method",
        "scan_scheduler_enabled",
        "scan_interval_minutes",
        "nvd_api_key_set",
        "nvd_min_seconds_between_calls",
    }


def test_the_nvd_key_is_never_echoed_back(client):
    """A local caller must not be able to read the key out of the app again."""
    r = client.post(
        "/api/system/settings",
        json={"nvd_api_key": "11111111-2222-3333-4444-555555555555"},
        headers=CSRF,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["nvd_api_key_set"] is True
    assert "nvd_api_key" not in body
    assert "5555" not in json.dumps(body), "the key value leaked into the response"
    # …and the pacing it buys is reported, so the user sees what the key bought
    assert body["nvd_min_seconds_between_calls"] < 1.0
    r2 = client.get("/api/system/settings")
    assert "nvd_api_key" not in r2.json()


def test_removing_the_nvd_key_restores_the_anonymous_pace(client):
    client.post("/api/system/settings", json={"nvd_api_key": "abc"}, headers=CSRF)
    r = client.post("/api/system/settings", json={"nvd_api_key": ""}, headers=CSRF)
    body = r.json()
    assert body["nvd_api_key_set"] is False
    assert body["nvd_min_seconds_between_calls"] > 6.0


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
