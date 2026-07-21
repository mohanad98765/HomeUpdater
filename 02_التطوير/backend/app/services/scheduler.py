"""Background scan scheduler (T7).

When ``settings.scan_scheduler_enabled`` is on, run an automatic network scan
every ``scan_interval_minutes``. Off by default: a scan should not run unattended
unless the user opts in. Reuses the same single-scan gate as POST /scan, so a
scheduled run never races a manual one.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from ..config import settings

_task: asyncio.Task | None = None


async def _loop() -> None:
    # Imported lazily to avoid import cycles at module load.
    from ..routers.devices import start_scan
    from ..services.network_utils import get_local_subnet

    interval = max(5, int(settings.scan_interval_minutes)) * 60
    logger.info(f"Scan scheduler enabled: every {settings.scan_interval_minutes} min")
    await asyncio.sleep(min(interval, 120))  # let startup settle before the first run
    while True:
        try:
            target = get_local_subnet()
            if target and start_scan(target):
                logger.info(f"Scheduled scan started on {target}")
            else:
                logger.debug("Scheduled scan skipped (no subnet or a scan is running)")
        except Exception as exc:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.warning(f"Scheduled scan failed to start: {exc}")
        await asyncio.sleep(interval)


def start() -> None:
    """Start the scheduler loop if enabled (no-op otherwise). Idempotent."""
    global _task
    if not settings.scan_scheduler_enabled:
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())


def stop() -> None:
    """Cancel the scheduler loop (called on shutdown)."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
    _task = None
