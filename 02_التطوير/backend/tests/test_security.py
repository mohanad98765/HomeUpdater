"""
Tests for the security middleware (Release blocker #1):
  - Host-header allowlist  -> DNS-rebinding protection (400)
  - X-HomeUpdater header on mutating requests -> CSRF protection (403)
"""

from __future__ import annotations


def test_allowed_host_get_ok(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_disallowed_host_rejected(client):
    r = client.get("/api/system/health", headers={"host": "evil.com"})
    assert r.status_code == 400
    body = r.json()
    assert "Host" in body["detail"]


def test_mutating_request_without_csrf_header_rejected(client):
    # No X-HomeUpdater header -> the CSRF guard blocks it before the endpoint runs.
    r = client.post("/api/devices/scan", json={})
    assert r.status_code == 403
    assert "X-HomeUpdater" in r.json()["detail"]


def test_disallowed_host_checked_before_csrf(client):
    # Bad host wins even on a mutating request (host check runs first).
    r = client.post("/api/devices/scan", json={}, headers={"host": "attacker.test"})
    assert r.status_code == 400


def test_get_requests_do_not_require_csrf_header(client):
    # Reads are exempt from the CSRF header requirement.
    r = client.get("/api/system/version")
    assert r.status_code == 200


def test_loopback_host_allowed_on_any_port(client):
    # The app may auto-select a free port; a loopback Host on a different port
    # must still pass (the DNS-rebinding check is hostname-only, port-agnostic).
    r = client.get("/api/system/health", headers={"host": "127.0.0.1:8137"})
    assert r.status_code == 200
    r2 = client.get("/api/system/health", headers={"host": "localhost:9042"})
    assert r2.status_code == 200


def test_nonloopback_host_still_rejected_regardless_of_port(client):
    r = client.get("/api/system/health", headers={"host": "evil.com:8000"})
    assert r.status_code == 400
