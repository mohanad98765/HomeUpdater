"""
Singleton scan progress tracker.

The discovery service updates this object at each phase of a scan, and
the API exposes it via GET /api/devices/scan/status so the UI can poll
for live progress while the long-running POST /scan request is in-flight.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Literal


Phase = Literal[
    "idle",
    "detecting",     # determining subnet/gateway
    "scanning",      # nmap ARP scan in progress
    "resolving",     # reverse-DNS lookups
    "classifying",   # device-type heuristics
    "done",
    "error",
]


@dataclass
class ProgressEvent:
    """One entry in the activity log."""
    elapsed_seconds: float
    phase: Phase
    message: str

    def to_dict(self) -> dict:
        return {
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "phase": self.phase,
            "message": self.message,
        }


@dataclass
class _ProgressState:
    """The mutable global state of the current/last scan."""
    is_running: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    subnet: str = ""
    phase: Phase = "idle"
    devices_count: int = 0
    last_message: str = ""
    error: str | None = None
    log: Deque[ProgressEvent] = field(default_factory=lambda: deque(maxlen=50))
    # Writer runs in an executor thread; readers hit /status concurrently.
    # The lock guards every append/clear/snapshot of `log` to avoid
    # "deque mutated during iteration" 500s while the UI polls.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # ---- mutators ------------------------------------------------
    def begin(self, subnet: str) -> None:
        self.is_running = True
        self.started_at = time.time()
        self.finished_at = None
        self.subnet = subnet
        self.phase = "detecting"
        self.devices_count = 0
        self.last_message = ""
        self.error = None
        with self._lock:
            self.log.clear()
        self.add(self.phase, f"Scan started on {subnet}")

    def set_phase(self, phase: Phase, message: str) -> None:
        self.phase = phase
        self.add(phase, message)

    def update_count(self, count: int, message: str = "") -> None:
        if count != self.devices_count:
            self.devices_count = count
            if message:
                self.add(self.phase, message)

    def finish(self, count: int) -> None:
        self.is_running = False
        self.devices_count = count
        self.finished_at = time.time()
        self.phase = "done"
        self.add("done", f"Scan complete - {count} device(s) found")

    def fail(self, error: str) -> None:
        self.is_running = False
        self.finished_at = time.time()
        self.phase = "error"
        self.error = error
        self.add("error", f"Scan failed: {error}")

    # ---- helpers -------------------------------------------------
    def _elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at if self.finished_at else time.time()
        return end - self.started_at

    def add(self, phase: Phase, message: str) -> None:
        """Append an event to the activity log."""
        self.last_message = message
        with self._lock:
            self.log.append(
                ProgressEvent(
                    elapsed_seconds=self._elapsed(),
                    phase=phase,
                    message=message,
                )
            )

    def to_dict(self) -> dict:
        with self._lock:
            events = list(self.log)
        return {
            "is_running": self.is_running,
            "phase": self.phase,
            "subnet": self.subnet,
            "devices_count": self.devices_count,
            "elapsed_seconds": round(self._elapsed(), 2),
            "last_message": self.last_message,
            "error": self.error,
            "log": [e.to_dict() for e in events],
        }


# Module-level singleton — imported by discovery.py and the router.
scan_progress = _ProgressState()
