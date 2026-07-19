"""
HomeUpdater Backend - FastAPI Entry Point.

This is the main application file. It:
1. Sets up logging (per WINDOWS_FUNDAMENTALS.md Section O.1)
2. Configures the FastAPI app with CORS for the frontend
3. Registers all API routers
4. Provides a healthy /api/health endpoint
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from . import __version__
from .config import settings
from .db import init_db
from .logging_setup import setup_logging
from .routers import android, devices, system, updates


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic."""
    setup_logging()
    logger.info("=" * 60)
    logger.info(f"Starting {settings.app_name} v{__version__}")
    logger.info(f"Database: {settings.database_url}")
    logger.info("=" * 60)

    # Phase 1.3: create tables on first run
    await init_db()

    yield  # ──── application runs here ────

    logger.info(f"Shutting down {settings.app_name}")


app = FastAPI(
    title=f"{settings.app_name} API",
    description="Home Network Universal Updater — Backend API",
    version=__version__,
    lifespan=lifespan,
)


# ─── Middleware ───────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Security guard: DNS-rebinding + CSRF (Release blocker #1) ────────
# The backend runs elevated (Administrator) and can install software, reboot
# the machine, and drive ADB. It binds to loopback, but a browser page on any
# site can still POST to 127.0.0.1:8000 (CSRF) and DNS-rebinding can bypass the
# CORS origin allowlist. This middleware closes both without passwords:
#   1) Host-header allowlist  -> blocks DNS rebinding (attacker host != loopback)
#   2) mandatory X-HomeUpdater header on state-changing methods -> forces a CORS
#      preflight for cross-origin callers, which the origin allowlist then blocks.
# The same-origin frontend always sends the header (see apiFetch in utils.ts).
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_guard(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    if host and host not in settings.allowed_hosts:
        logger.warning(f"Rejected request: disallowed Host header {host!r}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "مضيف غير مسموح به",
                "error_en": "Host not allowed",
                "detail": "Host header rejected (DNS-rebinding protection)",
            },
        )
    if request.method in _MUTATING_METHODS and request.headers.get("x-homeupdater") is None:
        logger.warning(
            f"Rejected {request.method} {request.url.path}: missing X-HomeUpdater header"
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": "طلب مرفوض",
                "error_en": "Forbidden",
                "detail": "Missing X-HomeUpdater header (CSRF protection)",
            },
        )
    return await call_next(request)


# ─── Global error handler (per WINDOWS_FUNDAMENTALS.md Section O.3) ───
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions: log technical details, return user-friendly message."""
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "حدث خطأ غير متوقع",
            "error_en": "An unexpected error occurred",
            "detail": "راجع السجلات للحصول على التفاصيل التقنية",
            "request_id": request.headers.get("x-request-id", "unknown"),
        },
    )


# ─── Routers ──────────────────────────────────────────────────────
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(updates.router, prefix="/api/updates", tags=["Updates"])
app.include_router(android.router, prefix="/api/android", tags=["Android"])


# ─── Root ─────────────────────────────────────────────────────────
@app.get("/")
async def root():
    """Welcome endpoint."""
    return {
        "name": settings.app_name,
        "name_ar": settings.app_name_ar,
        "version": __version__,
        "api_docs": "/docs",
        "status": "running",
    }


def run():
    """Run the server (used by `python -m app.main` or run.bat)."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
