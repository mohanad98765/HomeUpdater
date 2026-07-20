"""Aggregate capture/restore of every adaptive-timeout estimator, and the
disk-backed load/save on top of :mod:`adaptive_store`.

Kept separate from the individual services so the persistence policy (what gets
saved, when) lives in one place and the services stay unaware of storage.
"""

from __future__ import annotations

from loguru import logger

from . import discovery_python, homeassistant, ssh, windows_updates
from .adaptive_store import load_state, save_state


def capture_all() -> dict:
    """One snapshot of every estimator/ceiling, ready to serialize."""
    return {
        "scan": discovery_python.capture_estimators(),
        "ssh": ssh.capture_estimators(),
        "ha": homeassistant.capture_estimators(),
        "wua": windows_updates.capture_ceilings(),
    }


def restore_all(data: dict) -> None:
    """Warm-start every estimator/ceiling from a snapshot (tolerant of gaps)."""
    if not data:
        return
    discovery_python.restore_estimators(data.get("scan", {}))
    ssh.restore_estimators(data.get("ssh", {}))
    homeassistant.restore_estimators(data.get("ha", {}))
    windows_updates.restore_ceilings(data.get("wua", {}))


def load_from_disk() -> None:
    """Warm-start estimators from the persisted file (best-effort)."""
    try:
        restore_all(load_state())
    except Exception as exc:  # noqa: BLE001 — never fatal
        logger.warning(f"adaptive-timeout restore failed: {exc}")


def save_to_disk() -> None:
    """Persist the current estimator state (best-effort)."""
    try:
        save_state(capture_all())
    except Exception as exc:  # noqa: BLE001 — never fatal
        logger.warning(f"adaptive-timeout save failed: {exc}")
