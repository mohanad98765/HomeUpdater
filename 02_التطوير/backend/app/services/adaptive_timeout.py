"""
Adaptive network timeouts — client-side, generic, no server changes.

HomeUpdater's network work is two different problems, each with its own tool:

* **Reachability / connect** (the subnet scan, every probe/connect deadline) is
  *latency*-bound — many tiny round-trips with no payload. The right instrument
  is an RTO (retransmission timeout) estimated the way TCP does it
  (Jacobson-Karels, RFC 6298): ``RTO = SRTT + 4*RTTVAR``. It breathes with the
  network and never divides by anything, so there is no zero-throughput trap.

* **Open-ended transfers / installs** (winget, the Windows Update Agent, Home
  Assistant) have no client-known byte count and are not resumable, so a
  wall-clock deadline is the wrong tool — it either kills a slow-but-live install
  or lets a wedged one hang. The right instrument is a :class:`StallWatchdog`
  that aborts only when *progress* stops.

Between retries we use full-jitter backoff so a fleet of home devices waking
after a shared outage doesn't retry in lockstep (a retry storm).

Nothing here does any I/O; callers own the sockets/subprocesses and feed samples.
"""

from __future__ import annotations

import random
import time

# Sensible per-class clamp presets (seconds). Callers pick one; there is no
# single global clamp because a LAN probe and a WAN SSH connect live on very
# different scales (see the design doc).
LAN_SCAN_FLOOR = 0.5
LAN_SCAN_CEIL = 2.5
LAN_SCAN_INITIAL = 1.2  # matches the old PROBE_TIMEOUT so cold-start behaviour is unchanged

WAN_CONNECT_FLOOR = 2.0
WAN_CONNECT_CEIL = 30.0
WAN_CONNECT_INITIAL = 8.0


class AdaptiveNetworkTimeout:
    """A self-tuning RTO for reachability/connect deadlines (Jacobson-Karels).

    Feed every *successful* round-trip latency to :meth:`on_sample`; read the
    current deadline from :meth:`current`. The estimate reacts to jitter faster
    than to the mean (``beta > alpha``), so the deadline widens *before* the mean
    catches up — which is what stops legitimately-slow replies from timing out.

    The recurrence is purely additive, so unlike a throughput formula there is no
    division and no zero-rate blow-up.
    """

    def __init__(
        self,
        rto_min: float = LAN_SCAN_FLOOR,
        rto_max: float = LAN_SCAN_CEIL,
        rto_initial: float = LAN_SCAN_INITIAL,
        alpha: float = 1 / 8,
        beta: float = 1 / 4,
        k: int = 4,
        granularity: float = 0.001,
    ) -> None:
        if rto_min > rto_max:
            raise ValueError("rto_min must be <= rto_max")
        self.rto_min = rto_min
        self.rto_max = rto_max
        self.alpha = alpha
        self.beta = beta
        self.k = k
        self.g = granularity
        self.srtt: float | None = None
        self.rttvar: float | None = None
        # Cold start: no sample yet, so start from the initial guess (clamped).
        self.rto: float = self._clamp(rto_initial)

    def on_sample(self, rtt: float) -> float:
        """Fold a clean RTT sample in and return the updated RTO.

        Only pass RTTs from a first-try success (Karn's algorithm: never sample a
        retransmitted/retried request — its RTT is ambiguous). ``rtt <= 0`` is
        ignored so a bogus clock reading can't corrupt the estimate.
        """
        if rtt <= 0:
            return self.current()
        if self.srtt is None:
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            # RTTVAR uses the *old* SRTT, so update it first.
            self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - rtt)
            self.srtt = (1 - self.alpha) * self.srtt + self.alpha * rtt
        self.rto = self._clamp(self.srtt + max(self.g, self.k * self.rttvar))
        return self.rto

    def on_timeout(self) -> float:
        """Exponential backoff on a timeout (Jacobson). No sample is taken."""
        self.rto = self._clamp(self.rto * 2)
        return self.rto

    def stall_window(self, m: float = 3.0, floor: float = 2.0, ceiling: float = 15.0) -> float:
        """Derive a no-progress window from the RTO, so it inherits the path's tempo."""
        return min(max(m * self.current(), floor), ceiling)

    def current(self) -> float:
        """The deadline to use right now (always within the clamp)."""
        return self._clamp(self.rto)

    def _clamp(self, value: float) -> float:
        return min(max(value, self.rto_min), self.rto_max)

    # -- persistence helpers (used by the estimator registry) ----------------
    def to_dict(self) -> dict[str, float | None]:
        return {"srtt": self.srtt, "rttvar": self.rttvar, "rto": self.rto}

    def load_dict(self, data: dict) -> None:
        """Warm-start from a persisted snapshot; ignores malformed input."""
        try:
            srtt = data.get("srtt")
            rttvar = data.get("rttvar")
            rto = data.get("rto")
            if srtt is not None and rttvar is not None and srtt > 0 and rttvar >= 0:
                self.srtt = float(srtt)
                self.rttvar = float(rttvar)
            if rto is not None and rto > 0:
                self.rto = self._clamp(float(rto))
        except (TypeError, ValueError, AttributeError):
            pass  # a corrupt snapshot just means we start cold — never fatal


class StallWatchdog:
    """Aborts an open-ended operation when *progress* stops, not at a fixed clock.

    Built for opaque installers/transfers (winget, WUA, HA) whose size the client
    can't know and which can't be resumed: keep it alive while bytes / percent /
    output-lines keep arriving, and only abort after ``stall_window`` seconds of
    silence. An optional ``hard_ceiling`` bounds the whole operation regardless.
    """

    def __init__(self, stall_window: float, hard_ceiling: float | None = None) -> None:
        self.window = stall_window
        self.hard_ceiling = hard_ceiling
        self.started = time.monotonic()
        self.last_progress = self.started

    def progress(self, n: float = 1) -> None:
        """Call on any real progress (bytes, a percent tick, a line of output)."""
        if n > 0:
            self.last_progress = time.monotonic()

    def reset(self) -> None:
        now = time.monotonic()
        self.started = now
        self.last_progress = now

    def stalled(self) -> bool:
        now = time.monotonic()
        if self.hard_ceiling is not None and now - self.started > self.hard_ceiling:
            return True
        return (now - self.last_progress) > self.window

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_progress


class DurationCeiling:
    """Adaptive wall-clock ceiling for an *opaque, non-resumable* operation.

    Some operations (a WUA COM search/install, a ``winget`` listing) give no
    intra-call progress signal a watchdog could read, so a stall-watchdog can't
    help — the only honest bound is a wall-clock ceiling. Rather than a fixed
    one-size timeout, track an EWMA of *successful* durations and return
    ``ewma * safety`` clamped to ``[floor, ceiling]``: the bound tightens on a
    fast machine and widens on a slow one. Cold (no history) it returns the full
    ceiling — generous, because we don't yet know how long "normal" is.
    """

    def __init__(
        self,
        floor: float,
        ceiling: float,
        initial: float | None = None,
        safety: float = 3.0,
        weight: float = 0.3,
    ) -> None:
        if floor > ceiling:
            raise ValueError("floor must be <= ceiling")
        self.floor = floor
        self.ceiling = ceiling
        self.safety = safety
        self.weight = weight
        self.ewma: float | None = initial

    def timeout(self) -> float:
        base = self.ewma if self.ewma is not None else self.ceiling
        return min(max(base * self.safety, self.floor), self.ceiling)

    def observe(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.ewma = (
            seconds if self.ewma is None else (1 - self.weight) * self.ewma + self.weight * seconds
        )

    def to_dict(self) -> dict[str, float | None]:
        return {"ewma": self.ewma}

    def load_dict(self, data: dict) -> None:
        try:
            value = data.get("ewma")
            if value is not None and value > 0:
                self.ewma = float(value)
        except (TypeError, ValueError, AttributeError):
            pass


def backoff_with_jitter(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Full-jitter exponential backoff (AWS): uniform in ``[0, min(cap, base*2**n)]``.

    Full jitter (rather than a fixed or equal-jitter delay) de-correlates retries
    across many devices, which is what actually prevents a synchronized retry
    storm after a shared outage.
    """
    ceiling = min(cap, base * (2 ** max(0, attempt)))
    return random.uniform(0, ceiling)
