"""Home Assistant read timeouts are now a per-instance RTO (a LAN HA on a fast
box != one across a slower link), with a tight fixed connect leg."""

from __future__ import annotations

from app.services import homeassistant as ha
from app.services.homeassistant import _instance_estimator, _quick_timeout


def test_ha_estimator_is_per_instance_and_clamped():
    a = _instance_estimator("http://ha.local:8123")
    a2 = _instance_estimator("http://ha.local:8123")
    b = _instance_estimator("http://10.0.0.9:8123")
    assert a is a2
    assert a is not b
    assert a.current() == ha._HA_INITIAL  # cold start
    for _ in range(50):
        a.on_sample(0.02)  # fast LAN HA
    assert a.current() == ha._HA_FLOOR  # clamped to floor, never ~0


def test_quick_timeout_uses_learned_read_and_tight_connect():
    est = _instance_estimator("http://ha2.local:8123")
    for _ in range(50):
        est.on_sample(0.02)
    t = _quick_timeout("http://ha2.local:8123")
    assert t.connect == ha._CONNECT_TIMEOUT
    assert t.read == ha._HA_FLOOR  # adaptive read == the learned RTO
