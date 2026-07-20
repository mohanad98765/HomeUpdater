"""Adaptive timeout primitives (Jacobson-Karels RTO, stall watchdog, backoff).

These guard the invariants the whole v1.4.2 timeout work depends on:
  - cold start never aborts instantly nor waits forever,
  - the estimate is additive (no divide-by-zero trap),
  - the LAN floor is preserved (so the DTIM-sleeper capture can't regress),
  - the watchdog fires on *silence*, not on a fixed clock.
"""

from __future__ import annotations

import random
import time

from app.services.adaptive_timeout import (
    LAN_SCAN_CEIL,
    LAN_SCAN_FLOOR,
    LAN_SCAN_INITIAL,
    AdaptiveNetworkTimeout,
    StallWatchdog,
    backoff_with_jitter,
)


def test_cold_start_is_the_initial_guess():
    rto = AdaptiveNetworkTimeout()
    # No sample yet: usable value, neither ~0 (instant abort) nor huge (infinite wait).
    assert rto.current() == LAN_SCAN_INITIAL
    assert LAN_SCAN_FLOOR <= rto.current() <= LAN_SCAN_CEIL


def test_fast_lan_pins_to_floor_not_below():
    rto = AdaptiveNetworkTimeout()
    for _ in range(50):
        rto.on_sample(0.004)  # 4ms LAN
    # Sub-floor RTTs must NOT drive the deadline under the floor — below the floor
    # we'd be measuring host jitter, and (critically) we must keep enough headroom
    # that a power-save phone waking at DTIM still fits the retry window.
    assert rto.current() == LAN_SCAN_FLOOR


def test_slow_link_grows_but_capped_at_ceiling():
    rto = AdaptiveNetworkTimeout()
    for _ in range(50):
        rto.on_sample(5.0)  # pathologically slow
    assert rto.current() == LAN_SCAN_CEIL


def test_no_divide_by_zero_and_bogus_samples_ignored():
    rto = AdaptiveNetworkTimeout()
    before = rto.current()
    assert rto.on_sample(0) == before  # ignored
    assert rto.on_sample(-1.0) == before  # ignored
    # A single real sample must produce a finite, clamped value.
    val = rto.on_sample(0.05)
    assert LAN_SCAN_FLOOR <= val <= LAN_SCAN_CEIL


def test_variance_widens_the_deadline():
    # WAN-scale estimator so the effect isn't swallowed by the LAN floor.
    steady = AdaptiveNetworkTimeout(rto_min=0.05, rto_max=30.0, rto_initial=1.0)
    jumpy = AdaptiveNetworkTimeout(rto_min=0.05, rto_max=30.0, rto_initial=1.0)
    for _ in range(30):
        steady.on_sample(0.20)  # rock steady
    for r in [0.05, 0.40, 0.06, 0.38, 0.05, 0.42] * 5:
        jumpy.on_sample(r)  # same ~mean, high jitter
    # Same mean, more jitter -> larger RTO. That is the point of RTTVAR.
    assert jumpy.current() > steady.current()


def test_on_timeout_backs_off_and_caps():
    rto = AdaptiveNetworkTimeout(rto_min=0.5, rto_max=4.0, rto_initial=1.0)
    assert rto.on_timeout() == 2.0
    assert rto.on_timeout() == 4.0
    assert rto.on_timeout() == 4.0  # capped


def test_stall_window_derives_and_clamps():
    rto = AdaptiveNetworkTimeout(rto_min=0.5, rto_max=2.5, rto_initial=1.0)
    assert rto.stall_window(m=3, floor=2.0, ceiling=15.0) == 3.0
    # Tiny RTO still yields at least the floor window.
    small = AdaptiveNetworkTimeout(rto_min=0.01, rto_max=2.5, rto_initial=0.01)
    assert small.stall_window(m=3, floor=2.0, ceiling=15.0) == 2.0


def test_watchdog_not_stalled_while_progress_flows():
    wd = StallWatchdog(stall_window=0.05)
    for _ in range(5):
        wd.progress(1)
        time.sleep(0.02)  # < window, and progress keeps resetting it
        assert not wd.stalled()


def test_watchdog_fires_after_silence():
    wd = StallWatchdog(stall_window=0.05)
    wd.progress(1)
    time.sleep(0.08)
    assert wd.stalled()


def test_watchdog_hard_ceiling_bounds_even_with_progress():
    wd = StallWatchdog(stall_window=10.0, hard_ceiling=0.05)
    time.sleep(0.08)
    wd.progress(1)  # progressing, but the hard ceiling has passed
    assert wd.stalled()


def test_backoff_full_jitter_bounds_and_growth():
    random.seed(1234)
    prev_cap = 0.0
    for attempt in range(6):
        cap = min(60.0, 1.0 * (2**attempt))
        assert cap >= prev_cap
        prev_cap = cap
        for _ in range(50):
            d = backoff_with_jitter(attempt, base=1.0, cap=60.0)
            assert 0.0 <= d <= cap  # full jitter stays within [0, cap]


def test_persistence_round_trip_warm_starts():
    rto = AdaptiveNetworkTimeout(rto_min=0.05, rto_max=30.0, rto_initial=1.0)
    for _ in range(20):
        rto.on_sample(0.3)
    snapshot = rto.to_dict()
    warm = AdaptiveNetworkTimeout(rto_min=0.05, rto_max=30.0, rto_initial=1.0)
    warm.load_dict(snapshot)
    assert abs(warm.current() - rto.current()) < 1e-9
    # A corrupt snapshot must not raise and must leave a usable value.
    safe = AdaptiveNetworkTimeout()
    safe.load_dict({"srtt": "oops", "rttvar": None})
    assert safe.current() == LAN_SCAN_INITIAL
