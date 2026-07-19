"""
Tests for the updates router:
  - empty cached lists have the right shape
  - a check/install is rejected with 409 while another operation is running
"""

from __future__ import annotations

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
