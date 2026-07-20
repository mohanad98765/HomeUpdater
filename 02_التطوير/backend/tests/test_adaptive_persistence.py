"""Adaptive-timeout estimators persist across restarts (best-effort JSON store).
A missing/corrupt file must never raise — everything just starts cold."""

from __future__ import annotations

import json

from app.services import adaptive_persistence as ap
from app.services import adaptive_store, discovery_python, ssh


def test_capture_restore_round_trip():
    discovery_python._PROBE_ESTIMATORS.clear()
    ssh._CONNECT_ESTIMATORS.clear()
    est = discovery_python._probe_estimator("192.168.77.0/24")
    for _ in range(20):
        est.on_sample(0.8)  # lands between floor and ceil, distinct from cold 1.2
    learned = est.current()
    assert learned != discovery_python.PROBE_INITIAL

    snap = ap.capture_all()
    assert "192.168.77.0/24" in snap["scan"]

    discovery_python._PROBE_ESTIMATORS.clear()
    ap.restore_all(snap)
    restored = discovery_python._probe_estimator("192.168.77.0/24")
    assert abs(restored.current() - learned) < 1e-9


def test_disk_save_and_load(tmp_path, monkeypatch):
    fake = tmp_path / "adaptive_timeouts.json"
    monkeypatch.setattr(adaptive_store, "_path", lambda: fake)

    discovery_python._PROBE_ESTIMATORS.clear()
    est = discovery_python._probe_estimator("192.168.88.0/24")
    for _ in range(20):
        est.on_sample(0.8)
    ap.save_to_disk()
    assert fake.exists()
    data = json.loads(fake.read_text(encoding="utf-8"))
    assert "192.168.88.0/24" in data["scan"]

    discovery_python._PROBE_ESTIMATORS.clear()
    ap.load_from_disk()
    assert "192.168.88.0/24" in discovery_python._PROBE_ESTIMATORS


def test_missing_and_corrupt_file_are_tolerated(tmp_path, monkeypatch):
    fake = tmp_path / "adaptive_timeouts.json"
    monkeypatch.setattr(adaptive_store, "_path", lambda: fake)
    # Missing file.
    assert adaptive_store.load_state() == {}
    ap.load_from_disk()  # must not raise
    # Corrupt file.
    fake.write_text("{ not valid json", encoding="utf-8")
    assert adaptive_store.load_state() == {}
    ap.load_from_disk()  # must not raise
