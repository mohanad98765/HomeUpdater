"""Smoke tests: the core read endpoints respond with the expected shape."""

from __future__ import annotations


def test_api_welcome(client):
    # /api is the stable JSON welcome regardless of whether a frontend build exists.
    r = client.get("/api")
    assert r.status_code == 200
    assert r.json()["status"] == "running"


def test_root_responds(client):
    # "/" serves the SPA when a build exists, otherwise the dev JSON welcome.
    # Either way it must respond 200.
    r = client.get("/")
    assert r.status_code == 200


def test_health(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["version"]


def test_version(client):
    from app import __version__

    r = client.get("/api/system/version")
    assert r.status_code == 200
    assert r.json()["version"] == __version__  # tracks backend/VERSION


def test_devices_list_empty(client):
    r = client.get("/api/devices")
    assert r.status_code == 200
    body = r.json()
    assert body["devices"] == []
    assert body["total"] == 0


def test_devices_stats_empty(client):
    r = client.get("/api/devices/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["online"] == 0
    assert body["by_type"] == {}
