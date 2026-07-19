"""
Async SQLAlchemy engine + session factory.

Database lives at %APPDATA%\\HomeUpdater\\data\\homeupdater.db
(see config.get_data_dir).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models.orm import Base


# echo=False: keep SQL out of logs unless debugging
engine = create_async_engine(settings.database_url, echo=False, future=True)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Create tables if they do not exist. Called on app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized at {settings.database_url}")


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a fresh session per request."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
