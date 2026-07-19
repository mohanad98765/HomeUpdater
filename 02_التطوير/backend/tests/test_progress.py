"""
Concurrency test for the progress singletons.

The writer runs in an executor thread while the /status endpoint reads via
to_dict() on the event loop. Before the lock was added, this raised
"deque mutated during iteration" and surfaced as intermittent 500s.
"""

from __future__ import annotations

import threading

from app.services.progress import _ProgressState
from app.services.update_progress import _UpdateProgress


def test_scan_progress_survives_concurrent_read_write():
    state = _ProgressState()
    state.begin("10.0.0.0/24")
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            state.set_phase("scanning", f"found device {i}")
            i += 1

    def reader():
        try:
            for _ in range(5000):
                snapshot = state.to_dict()
                # Force iteration of the copied log to catch mutation errors.
                _ = [e["message"] for e in snapshot["log"]]
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)
        finally:
            stop.set()

    w = threading.Thread(target=writer, daemon=True)
    r = threading.Thread(target=reader, daemon=True)
    w.start()
    r.start()
    r.join(timeout=10)
    stop.set()
    w.join(timeout=2)

    assert not errors, f"concurrent access raised: {errors[0]!r}"


def test_update_progress_survives_concurrent_read_write():
    state = _UpdateProgress()
    state.begin("check", total=10)
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            state.update_progress(completed=i % 10, total=10, message=f"item {i}")
            i += 1

    def reader():
        try:
            for _ in range(5000):
                _ = state.to_dict()["log"]
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            stop.set()

    w = threading.Thread(target=writer, daemon=True)
    r = threading.Thread(target=reader, daemon=True)
    w.start()
    r.start()
    r.join(timeout=10)
    stop.set()
    w.join(timeout=2)

    assert not errors, f"concurrent access raised: {errors[0]!r}"
