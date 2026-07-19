"""Tests for the decoupled desktop-notification dispatch."""

from __future__ import annotations

import pytest

from app.services import notifications
from tests.conftest import CSRF_HEADER


@pytest.fixture(autouse=True)
def _clear_sink():
    notifications.set_sink(None)
    yield
    notifications.set_sink(None)


def test_notify_without_sink_returns_false():
    assert notifications.notify("Title", "Message") is False


def test_notify_dispatches_to_sink():
    calls = []
    notifications.set_sink(lambda title, msg: calls.append((title, msg)))
    assert notifications.notify("Title", "Message") is True
    assert calls == [("Title", "Message")]


def test_notify_survives_sink_error():
    def boom(_title, _msg):
        raise RuntimeError("sink failed")

    notifications.set_sink(boom)
    assert notifications.notify("Title", "Message") is False


def test_notify_test_endpoint(client):
    # No tray sink during tests -> handled is False, but the endpoint still 200s.
    r = client.post("/api/system/notify-test", json={}, headers=CSRF_HEADER)
    assert r.status_code == 200
    assert r.json()["sent"] is False
