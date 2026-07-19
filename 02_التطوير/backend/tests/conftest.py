"""
Shared pytest fixtures.

The FastAPI app is exercised through Starlette's TestClient. We deliberately
do NOT enter the TestClient context manager, so the app lifespan (which would
call init_db() on the *real* %APPDATA% database) never runs — tests use an
isolated temp SQLite file via a dependency override instead.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.orm import Base
from app.services.progress import scan_progress
from app.services.update_progress import update_progress

# The security middleware only allows loopback Host headers; TestClient's
# default "testserver" host would be rejected, so pin an allowed base URL.
ALLOWED_BASE = "http://127.0.0.1:8000"

# Header the CSRF guard requires on state-changing requests.
CSRF_HEADER = {"X-HomeUpdater": "1"}


@pytest.fixture
def client(tmp_path):
    """A TestClient wired to an isolated temp SQLite database."""
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_async_engine(db_url, future=True, poolclass=NullPool)
    TestSession = async_sessionmaker(
        engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_tables())

    async def _get_db_override():
        async with TestSession() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db_override

    # Reset shared singletons so one test's state never leaks into the next.
    scan_progress.is_running = False
    update_progress.is_running = False

    test_client = TestClient(app, base_url=ALLOWED_BASE)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
