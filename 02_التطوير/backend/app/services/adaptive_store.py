"""Best-effort on-disk persistence for the adaptive-timeout estimators.

Estimators warm-start across app restarts so the FIRST scan/connect after a
restart begins from the measured value instead of the cold guess. This is a
convenience, never a correctness dependency: a missing or corrupt file just
means everything starts cold. All failures are swallowed and logged — the store
must never break a scan or an update.

A lightweight JSON file (not a DB table) keeps it dependency-free and trivially
inspectable; the data is tiny (a handful of floats per subnet/endpoint).
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from ..config import get_data_dir

_FILENAME = "adaptive_timeouts.json"


def _path() -> Path:
    return get_data_dir() / _FILENAME


def load_state() -> dict:
    """Return the persisted snapshot, or {} if absent/unreadable/corrupt."""
    try:
        path = _path()
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        logger.warning(f"adaptive-timeout store: load failed ({exc}); starting cold")
        return {}


def save_state(data: dict) -> None:
    """Write the snapshot atomically-ish; never raise."""
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic on the same filesystem
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        logger.warning(f"adaptive-timeout store: save failed ({exc})")
