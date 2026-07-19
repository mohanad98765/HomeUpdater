"""
Async SQLAlchemy engine + session factory.

Database lives at %APPDATA%\\HomeUpdater\\data\\homeupdater.db
(see config.get_data_dir).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models.orm import Base  # noqa: F401  (imported so metadata is registered)

# echo=False: keep SQL out of logs unless debugging
engine = create_async_engine(settings.database_url, echo=False, future=True)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)


def _run_migrations() -> None:
    """Bring the database schema up to head via Alembic (runs synchronously).

    Handles three cases so startup never crashes:
      * fresh DB          -> `upgrade head` creates every table.
      * Alembic-managed DB -> `upgrade head` applies any new revisions.
      * legacy create_all DB (tables exist, no alembic_version) -> `stamp head`,
        because a create_all schema already matches the current models.
    """
    from sqlalchemy import create_engine, inspect

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    sync_url = settings.database_url.replace("sqlite+aiosqlite://", "sqlite://")
    probe = create_engine(sync_url)
    try:
        tables = set(inspect(probe).get_table_names())
    finally:
        probe.dispose()

    if "devices" in tables and "alembic_version" not in tables:
        logger.warning("Adopting pre-Alembic database: stamping current head")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


async def init_db() -> None:
    """Apply database migrations. Called on app startup."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_migrations)
    logger.info(f"Database migrated to head at {settings.database_url}")


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a fresh session per request."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
