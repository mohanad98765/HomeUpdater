"""
Desktop notifications (Windows toast via the tray icon).

The tray app registers a "sink" that shows a balloon/toast from its tray icon
(pystray's ``Icon.notify``). When the backend runs without a tray — the dev
server or the Windows Service — no sink is registered and notifications are
logged instead. This keeps the backend fully decoupled from any GUI toolkit,
so importing this module never pulls in pystray.
"""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

# A sink receives (title, message) and displays it however it can.
NotificationSink = Callable[[str, str], None]

_sink: NotificationSink | None = None


def set_sink(sink: NotificationSink | None) -> None:
    """Register (or clear, with None) the notification sink. Called by the tray."""
    global _sink
    _sink = sink


def notify(title: str, message: str) -> bool:
    """Show a desktop notification.

    Returns True if a sink handled it, False if it was only logged (no tray) or
    the sink raised.
    """
    if _sink is None:
        logger.info(f"[notify] {title} — {message}")
        return False
    try:
        _sink(title, message)
        return True
    except Exception:
        logger.exception("notification sink failed")
        return False
