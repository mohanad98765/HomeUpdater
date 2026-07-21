"""
HomeUpdater Backend - FastAPI Entry Point.

This is the main application file. It:
1. Sets up logging (per WINDOWS_FUNDAMENTALS.md Section O.1)
2. Configures the FastAPI app with CORS for the frontend
3. Registers all API routers
4. Provides a healthy /api/health endpoint
"""

import hmac
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from . import __version__
from .config import settings
from .db import init_db
from .logging_setup import setup_logging
from .routers import (
    advisor,
    android,
    auth,
    devices,
    homeassistant,
    security,
    ssh,
    system,
    updates,
    winrm_hosts,
)
from .services import auth as auth_svc


def _get_frontend_dist() -> Path | None:
    """Locate the built frontend (frontend/dist) for production single-server mode.

    Returns None in development (no build), where the Vite dev server serves the
    UI instead. Checked locations, in order:
      1. HOMEUPDATER_FRONTEND_DIST env var (explicit override)
      2. PyInstaller bundle: <_MEIPASS>/frontend_dist
      3. Source tree: 02_التطوير/frontend/dist
    """
    import os

    override = os.environ.get("HOMEUPDATER_FRONTEND_DIST")
    candidates = []
    if override:
        candidates.append(Path(override))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend_dist")
    # app/ -> backend/ -> 02_التطوير/ -> frontend/dist
    candidates.append(Path(__file__).resolve().parent.parent.parent / "frontend" / "dist")

    for path in candidates:
        if path.is_dir() and (path / "index.html").is_file():
            return path
    return None


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

    # Warm-start the adaptive network timeouts from disk (best-effort).
    if settings.adaptive_timeout_persistence:
        from .services import adaptive_persistence

        adaptive_persistence.load_from_disk()

    # Background scan scheduler (opt-in via settings.scan_scheduler_enabled).
    from .services import scheduler

    scheduler.start()

    yield  # ──── application runs here ────

    scheduler.stop()
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


def _hostname_only(host: str) -> str:
    """Strip the :port (and IPv6 brackets) from a Host header value."""
    if host.startswith("["):  # [::1]:8000 or [::1]
        return host[1 : host.index("]")] if "]" in host else host[1:]
    if ":" in host:
        return host.rsplit(":", 1)[0]
    return host


# The DNS-rebinding defense only cares about the HOSTNAME (an attacker uses a
# domain that resolves to loopback) — not the port. Checking the hostname alone
# lets the app run on any auto-selected port (find_free_port) without every
# request being rejected. Derived from the configured allowlist.
_ALLOWED_HOSTNAMES = {_hostname_only(h.lower()) for h in settings.allowed_hosts}

# /api/* paths exempt from the session-token requirement: liveness only, no
# sensitive data and no side effects — so the connection indicator works even
# before the SPA has read its token.
_TOKEN_EXEMPT_PATHS = {"/api/system/health", "/api/system/version"}
# Also gate the API root (welcome payload) and the interactive API docs (they
# expose app metadata / the full endpoint surface).
_TOKEN_GATED_EXACT = {"/api", "/docs", "/redoc", "/openapi.json"}


def _needs_token(path: str) -> bool:
    if path in _TOKEN_EXEMPT_PATHS:
        return False
    return path.startswith("/api/") or path in _TOKEN_GATED_EXACT


# App-level login gate (user password). Once a password is configured, every
# sensitive /api/* route requires a valid login session (X-HomeUpdater-Auth).
# The auth endpoints themselves + liveness are exempt so the UI can render the
# setup/login screen before the user is authenticated.
_AUTH_EXEMPT_PATHS = {
    "/api/system/health",
    "/api/system/version",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/setup",
}


def _needs_app_auth(path: str) -> bool:
    if path in _AUTH_EXEMPT_PATHS:
        return False
    # Cover the same doc/openapi/root paths the token gate protects, so a
    # token-holder that hasn't logged in can't enumerate the API surface either.
    return path.startswith("/api/") or path in _TOKEN_GATED_EXACT


@app.middleware("http")
async def security_guard(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    if host and _hostname_only(host) not in _ALLOWED_HOSTNAMES:
        logger.warning(f"Rejected request: disallowed Host header {host!r}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "مضيف غير مسموح به",
                "error_en": "Host not allowed",
                "detail": "Host header rejected (DNS-rebinding protection)",
            },
        )
    # Session-token auth: the loopback API runs ELEVATED, and loopback TCP is
    # reachable by any local user/process — the Host/CSRF checks only stop
    # browsers. Require a per-launch secret (which only the legitimate UI got, via
    # its launch URL) on every /api/* call, so another local account or a curl/
    # malware process can't drive install/reboot. Not enforced when unset (dev).
    token = settings.session_token
    if token and _needs_token(request.url.path):
        provided = request.headers.get("x-homeupdater-token", "")
        if not hmac.compare_digest(provided, token):
            logger.warning(f"Rejected {request.method} {request.url.path}: bad/missing token")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "غير مُصرَّح",
                    "error_en": "Unauthorized",
                    "detail": "Missing or invalid session token",
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
    # App-level login gate: once the user has SET a password, sensitive routes
    # require a valid login session. Before any password is set the gate is off
    # (the UI forces first-run setup), so a fresh install behaves as before.
    if auth_svc.is_password_set() and _needs_app_auth(request.url.path):
        if not auth_svc.is_session_valid(request.headers.get("x-homeupdater-auth", "")):
            logger.warning(f"Rejected {request.method} {request.url.path}: login required")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "يلزم تسجيل الدخول",
                    "error_en": "Login required",
                    "detail": "Missing or invalid login session",
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
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(updates.router, prefix="/api/updates", tags=["Updates"])
app.include_router(android.router, prefix="/api/android", tags=["Android"])
app.include_router(security.router, prefix="/api/security", tags=["Security"])
app.include_router(homeassistant.router, prefix="/api/homeassistant", tags=["HomeAssistant"])
app.include_router(ssh.router, prefix="/api/ssh", tags=["SSH"])
app.include_router(winrm_hosts.router, prefix="/api/winrm", tags=["WinRM"])
app.include_router(advisor.router, prefix="/api/advisor", tags=["Advisor"])


# ─── API welcome (always available) ───────────────────────────────
@app.get("/api")
async def api_root():
    """Welcome / liveness payload for the API."""
    return {
        "name": settings.app_name,
        "name_ar": settings.app_name_ar,
        "version": __version__,
        "api_docs": "/docs",
        "status": "running",
    }


# ─── Frontend ─────────────────────────────────────────────────────
# In production (a build exists) the backend serves the SPA at "/", so the whole
# app is one server. In development there is no build, so "/" returns the JSON
# welcome and the Vite dev server serves the UI. Mounted LAST so it never
# shadows the /api/* routers or /docs.
_frontend_dist = _get_frontend_dist()
if _frontend_dist is not None:
    logger.info(f"Serving frontend build from {_frontend_dist}")
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:

    @app.get("/")
    async def root():
        """Dev-mode welcome (no frontend build present)."""
        return {
            "name": settings.app_name,
            "version": __version__,
            "status": "running",
            "note": "frontend build not found — using Vite dev server",
        }


def run():
    """Run the server (used by `python -m app.main` or run.bat)."""
    import uvicorn

    from .config import find_free_port

    port = find_free_port(settings.port, settings.host)
    if port != settings.port:
        logger.info(f"Port {settings.port} busy — using {port} instead")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
