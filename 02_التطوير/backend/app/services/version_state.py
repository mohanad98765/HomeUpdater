"""Detect an already-applied upgrade on launch, safely.

The signed installer replaces the files and relaunches the app; we do NOT
auto-download or self-elevate (see routers/system.py — that would train users to
click through SmartScreen). Instead, on every startup we compare the current
``__version__`` against the last version we persisted. If it went up, an upgrade
happened between runs, so we surface a one-time "upgraded from X to Y" notice
(desktop toast + an endpoint the UI reads once). Purely local, no elevation, no
forced restart. Every disk op is best-effort and never raises — a failure here
must never block startup.
"""

from __future__ import annotations

import json

from loguru import logger

from ..config import get_data_dir

_STATE_FILE = "version_state.json"

# The upgrade notice for THIS process, filled once at startup by
# detect_and_record(). Stays constant for the session; the UI shows it once and
# suppresses repeats via localStorage.
_notice: dict = {"upgraded": False, "previous": None, "current": None}


def _path():
    return get_data_dir() / _STATE_FILE


def _ver_tuple(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a comparable int tuple (non-digits stripped)."""
    parts = [int("".join(c for c in p if c.isdigit()) or 0) for p in str(v).split(".")]
    return tuple(parts) or (0,)


def read_last_seen() -> str | None:
    """The version recorded on the previous run, or None if never recorded."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        v = data.get("last_seen_version")
        return str(v) if v else None
    except Exception:
        return None  # missing/corrupt file → treated as first run


def write_last_seen(version: str) -> None:
    """Persist the current version atomically. Best-effort; never raises."""
    try:
        target = _path()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps({"last_seen_version": str(version)}), encoding="utf-8")
        tmp.replace(target)
    except Exception as exc:  # noqa: BLE001 — persistence must not break startup
        logger.warning(f"version_state: could not persist last-seen version: {exc}")


def detect_and_record(current: str) -> dict:
    """Compare the persisted last-seen version to ``current`` and record current.

    Returns the session upgrade notice ``{upgraded, previous, current}``. The
    first-ever run records the version silently (upgraded=False). An upgrade is
    reported only when ``current`` is strictly newer than the last-seen version;
    a downgrade or equal version reports upgraded=False.
    """
    global _notice
    previous = read_last_seen()
    upgraded = bool(previous) and _ver_tuple(current) > _ver_tuple(previous)
    _notice = {
        "upgraded": upgraded,
        "previous": previous if upgraded else None,
        "current": current,
    }
    if previous != current:
        write_last_seen(current)  # advance the stored version (also seeds first run)
    return _notice


def get_notice() -> dict:
    """The upgrade notice detected at startup (constant for the session)."""
    return _notice
