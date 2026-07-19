"""
Singleton update-operation progress tracker (mirror of scan_progress).

Used for both "check for updates" and "install updates" runs so the UI
can show a live activity log via GET /api/updates/windows/status.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

Phase = Literal[
    "idle",
    "checking",  # searching Windows Update for pending items
    "downloading",
    "installing",
    "rebooting",
    "done",
    "error",
]


@dataclass
class UpdateEvent:
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
class _UpdateProgress:
    is_running: bool = False
    operation: str = ""  # "check" or "install"
    started_at: float | None = None
    finished_at: float | None = None
    phase: Phase = "idle"
    total: int = 0
    completed: int = 0
    last_message: str = ""
    error: str | None = None
    log: deque[UpdateEvent] = field(default_factory=lambda: deque(maxlen=80))
    # Guards log append/clear/snapshot against the concurrent /status reader.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ---- mutators ---------------------------------------------------
    def begin(self, operation: str, total: int = 0) -> None:
        self.is_running = True
        self.operation = operation
        self.started_at = time.time()
        self.finished_at = None
        self.phase = "checking" if operation == "check" else "downloading"
        self.total = total
        self.completed = 0
        self.last_message = ""
        self.error = None
        with self._lock:
            self.log.clear()
        self.add(self.phase, f"Starting {operation}")

    def set_phase(self, phase: Phase, message: str) -> None:
        self.phase = phase
        self.add(phase, message)

    def update_progress(self, completed: int, total: int | None = None, message: str = "") -> None:
        if total is not None:
            self.total = total
        self.completed = completed
        if message:
            self.add(self.phase, message)

    def finish(self, message: str = "Done") -> None:
        self.is_running = False
        self.finished_at = time.time()
        self.phase = "done"
        self.add("done", message)

    def fail(self, error: str) -> None:
        self.is_running = False
        self.finished_at = time.time()
        self.phase = "error"
        self.error = error
        self.add("error", f"Failed: {error}")

    def reboot_required(self) -> None:
        """Mark that a reboot is required to complete the install."""
        self.phase = "rebooting"
        self.add("rebooting", "Reboot required to finish installing updates")

    # ---- helpers ----------------------------------------------------
    def _elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at if self.finished_at else time.time()
        return end - self.started_at

    def add(self, phase: Phase, message: str) -> None:
        self.last_message = message
        with self._lock:
            self.log.append(
                UpdateEvent(
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
            "operation": self.operation,
            "phase": self.phase,
            "total": self.total,
            "completed": self.completed,
            "elapsed_seconds": round(self._elapsed(), 2),
            "last_message": self.last_message,
            "error": self.error,
            "log": [e.to_dict() for e in events],
        }


# Module singleton
update_progress = _UpdateProgress()
