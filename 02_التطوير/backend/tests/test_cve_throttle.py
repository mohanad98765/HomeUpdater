"""NVD pacing is AIMD now: back off multiplicatively on 429/403 (honoring
Retry-After), narrow back additively to the safe floor on success — never below
the floor, since anonymous callers have no headroom to speed up."""

from __future__ import annotations

import httpx

from app.services.cve import _NvdThrottle, _retry_after_seconds


def test_throttle_starts_at_floor_and_never_below():
    t = _NvdThrottle(floor=6.5, ceiling=120.0)
    assert t.current() == 6.5
    t.on_success()
    assert t.current() == 6.5  # already at the safe rate; never below


def test_backs_off_multiplicatively_on_rate_limit():
    t = _NvdThrottle(floor=6.5, ceiling=120.0)
    t.on_rate_limited()
    assert t.current() == 13.0
    t.on_rate_limited()
    assert t.current() == 26.0


def test_honors_retry_after_when_larger():
    t = _NvdThrottle(floor=6.5, ceiling=120.0)
    t.on_rate_limited(retry_after=60)
    assert t.current() == 60.0  # max(2*6.5, 60)


def test_backoff_capped_at_ceiling():
    t = _NvdThrottle(floor=6.5, ceiling=30.0)
    for _ in range(10):
        t.on_rate_limited()
    assert t.current() == 30.0


def test_narrows_back_to_floor_after_sustained_success():
    t = _NvdThrottle(floor=6.5, ceiling=120.0)
    t.on_rate_limited()
    t.on_rate_limited()  # 26.0
    t.on_success()
    assert t.current() == 25.0  # additive decrease
    for _ in range(100):
        t.on_success()
    assert t.current() == 6.5  # all the way back, never under the floor


def test_retry_after_parsing_seconds_only():
    assert _retry_after_seconds(httpx.Response(429, headers={"Retry-After": "42"})) == 42.0
    assert _retry_after_seconds(httpx.Response(429)) is None
    # HTTP-date form is not seconds; we don't parse it (return None, no crash).
    assert (
        _retry_after_seconds(httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2099"}))
        is None
    )
