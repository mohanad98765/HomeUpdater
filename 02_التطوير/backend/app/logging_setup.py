r"""
Logging configuration for HomeUpdater.

Implements the Logging requirements from WINDOWS_FUNDAMENTALS.md (Section O.1):
- 5 levels (DEBUG / INFO / WARNING / ERROR / CRITICAL)
- File rotation (size-based)
- Retention (days)
- Logs go to %APPDATA%\HomeUpdater\logs\
"""

import sys

from loguru import logger

from .config import get_logs_dir, settings


def setup_logging() -> None:
    """Configure loguru with file rotation and console output."""
    # Remove default handler
    logger.remove()

    # Console handler (human-readable, colored)
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler with rotation
    log_file = get_logs_dir() / "homeupdater_{time:YYYY-MM-DD}.log"
    logger.add(
        log_file,
        level=settings.log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        rotation=f"{settings.log_rotation_size_mb} MB",
        retention=f"{settings.log_retention_days} days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # async-safe
    )

    logger.info(f"Logging initialized at level={settings.log_level}")
    logger.info(f"Log files location: {get_logs_dir()}")
