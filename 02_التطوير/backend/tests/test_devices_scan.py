"""
Regression tests for the devices scan endpoint:
  - two MAC-less hosts no longer crash the scan (the mac UNIQUE-on-"" bug)
  - a concurrent scan is rejected with 409
"""

from __future__ import annotations

from app.services.progress import scan_progress
from tests.conftest import CSRF_HEADER


def _fake_scan_result():
    return {
        "subnet": "10.0.0.0/24",
        "devices": [
            # Two devices with NO MAC — used to violate the UNIQUE("") constraint.
            {"mac": "", "ip": "10.0.0.2", "hostname": "", "vendor": "", "device_type": "unknown"},
            {
                "mac": "",
                "ip": "10.0.0.3",
                "hostname": "h3",
                "vendor": "Dell",
                "device_type": "computer",
            },
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ip": "10.0.0.1",
                "hostname": "router",
                "vendor": "TP-Link",
                "device_type": "router",
            },
        ],
    }


def test_two_macless_devices_do_not_crash_scan(client, monkeypatch):
    async def fake_scan(subnet):
        return _fake_scan_result()

    monkeypatch.setattr("app.routers.devices.scan_network", fake_scan)

    r = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["new"] == 3
    # Both MAC-less devices persisted; their wire "mac" is "" (never null).
    macless = [d for d in body["devices"] if d["mac"] == ""]
    assert len(macless) == 2


def test_rescan_updates_without_duplicating(client, monkeypatch):
    async def fake_scan(subnet):
        return _fake_scan_result()

    monkeypatch.setattr("app.routers.devices.scan_network", fake_scan)

    first = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER).json()
    scan_progress.is_running = False  # fake scan does not reset the singleton
    second = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER).json()

    assert first["total"] == second["total"] == 3
    assert second["new"] == 0  # nothing new on the second pass


def test_duplicate_mac_in_one_scan_does_not_crash(client, monkeypatch):
    # Two IPs sharing one MAC (ARP proxy / router alias) must not violate
    # UNIQUE(devices.mac) — they collapse to a single device row.
    async def fake_scan(subnet):
        return {
            "subnet": "10.0.0.0/24",
            "devices": [
                {
                    "mac": "AA:BB:CC:00:00:01",
                    "ip": "10.0.0.5",
                    "hostname": "",
                    "vendor": "",
                    "device_type": "unknown",
                },
                {
                    "mac": "AA:BB:CC:00:00:01",
                    "ip": "10.0.0.6",
                    "hostname": "",
                    "vendor": "",
                    "device_type": "unknown",
                },
            ],
        }

    monkeypatch.setattr("app.routers.devices.scan_network", fake_scan)
    r = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1  # deduped by MAC
    assert body["new"] == 1


def test_concurrent_scan_rejected(client):
    scan_progress.is_running = True
    try:
        r = client.post("/api/devices/scan", json={}, headers=CSRF_HEADER)
        assert r.status_code == 409
    finally:
        scan_progress.is_running = False
