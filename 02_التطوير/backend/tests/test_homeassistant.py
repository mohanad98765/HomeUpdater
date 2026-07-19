"""Tests for the Home Assistant integration (HTTP to HA is monkeypatched)."""

from __future__ import annotations

from app.services import homeassistant as ha
from tests.conftest import CSRF_HEADER

SAMPLE_STATE = {
    "entity_id": "update.router_firmware",
    "state": "on",
    "attributes": {
        "friendly_name": "Router Firmware",
        "title": "Router",
        "installed_version": "1.0.0",
        "latest_version": "1.1.0",
        "release_summary": "Security fixes",
        "release_url": "https://example.com",
    },
}


def test_parse_update_entity_available():
    e = ha.parse_update_entity(SAMPLE_STATE)
    assert e["entity_id"] == "update.router_firmware"
    assert e["update_available"] is True
    assert e["installed_version"] == "1.0.0"
    assert e["latest_version"] == "1.1.0"
    assert e["title"] == "Router"


def test_parse_update_entity_up_to_date():
    e = ha.parse_update_entity({**SAMPLE_STATE, "state": "off"})
    assert e["update_available"] is False


def test_status_not_configured(client):
    r = client.get("/api/homeassistant/status")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_config_verifies_and_never_leaks_token(client, monkeypatch):
    async def fake_check(base_url, token):
        return {"connected": True, "version": "2024.7.1", "location_name": "Home"}

    monkeypatch.setattr(ha, "check", fake_check)
    r = client.post(
        "/api/homeassistant/config",
        json={"base_url": "http://ha.local:8123", "token": "secret", "enabled": True},
        headers=CSRF_HEADER,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["connected"] is True
    assert body["version"] == "2024.7.1"
    assert body["has_token"] is True
    assert "token" not in body  # the secret is never returned


def test_config_rejects_bad_connection(client, monkeypatch):
    async def bad_check(base_url, token):
        raise ha.HAError("Invalid token (401)")

    monkeypatch.setattr(ha, "check", bad_check)
    r = client.post(
        "/api/homeassistant/config",
        json={"base_url": "http://ha.local:8123", "token": "bad", "enabled": True},
        headers=CSRF_HEADER,
    )
    assert r.status_code == 400


def test_updates_requires_config(client):
    r = client.get("/api/homeassistant/updates")
    assert r.status_code == 400


def test_updates_returns_available(client, monkeypatch):
    async def fake_check(base_url, token):
        return {"connected": True, "version": "x", "location_name": "y"}

    async def fake_updates(base_url, token):
        return {"total": 2, "available": [ha.parse_update_entity(SAMPLE_STATE)], "up_to_date": 1}

    monkeypatch.setattr(ha, "check", fake_check)
    monkeypatch.setattr(ha, "get_updates", fake_updates)
    client.post(
        "/api/homeassistant/config",
        json={"base_url": "http://ha.local:8123", "token": "abc", "enabled": True},
        headers=CSRF_HEADER,
    )
    r = client.get("/api/homeassistant/updates")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["available"]) == 1
    assert body["available"][0]["latest_version"] == "1.1.0"
