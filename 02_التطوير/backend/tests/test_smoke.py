"""Smoke tests: the core read endpoints respond with the expected shape."""

from __future__ import annotations


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "running"


def test_health(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["version"]


def test_version(client):
    r = client.get("/api/system/version")
    assert r.status_code == 200
    assert r.json()["version"] == "0.1.0"


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
