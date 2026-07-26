"""A second, TLS-only listener that serves the agent endpoints and nothing else.

The obvious approach — put TLS on the existing listener and bind it to the network —
is the wrong one. That listener serves an API running with administrator rights on the
operator's PC: the whole update, install and settings surface. Exposing it to the LAN
to make three agent endpoints reachable would trade the product's core safety property
for a feature.

So: a separate uvicorn instance, its own port, TLS required, and an allowlist of three
exact paths. Anything else on this socket gets 404 before a route is even matched, so
adding an operator endpoint under /api/agents later cannot silently publish it to the
network. Off by default — a new listening socket on a customer's machine is a decision
the customer makes, not a side effect of upgrading.
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.requests import Request

from .config import settings
from .routers import agents as agents_router
from .services import agent_tls

# The three paths an agent actually calls. Exact strings, never a prefix — the same
# rule the hub's own auth exemptions follow, for the same reason.
AGENT_PATHS = frozenset(
    {"/api/agents/enrol", "/api/agents/checkin", "/api/agents/result", "/api/system/health"}
)


def build_app() -> FastAPI:
    app = FastAPI(
        title="HomeUpdater Agent Listener",
        docs_url=None,  # no interactive docs on a network-facing socket
        redoc_url=None,
        openapi_url=None,  # …and no schema to enumerate it from
    )

    @app.middleware("http")
    async def only_agent_paths(request: Request, call_next):
        if request.url.path not in AGENT_PATHS:
            # 404, not 403: this socket does not admit that the other API exists.
            return JSONResponse(status_code=404, content={"detail": "not_found"})
        return await call_next(request)

    app.include_router(agents_router.router, prefix="/api/agents", tags=["Agents"])

    @app.get("/api/system/health")
    async def health() -> dict:
        # Enough for an agent to see the hub is up; nothing about the hub's contents.
        return {"status": "ok", "listener": "agent"}

    return app


class AgentListener:
    """Owns the second uvicorn server. Start/stop is idempotent."""

    def __init__(self) -> None:
        self._server = None
        self._thread: threading.Thread | None = None
        self.error: str = ""

    @property
    def running(self) -> bool:
        return bool(self._server and getattr(self._server, "started", False))

    def start(self) -> dict:
        if self.running:
            return self.status()
        import uvicorn

        details = agent_tls.ensure_cert()
        config = uvicorn.Config(
            build_app(),
            host=settings.agent_listener_host,
            port=settings.agent_listener_port,
            ssl_certfile=str(agent_tls.cert_path()),
            ssl_keyfile=str(agent_tls.key_path()),
            log_config=None,
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self.error = ""

        def run() -> None:
            try:
                asyncio.run(self._server.serve())
            except Exception as exc:  # noqa: BLE001 — a dead listener must be visible
                self.error = str(exc)
                logger.error(f"agent listener stopped: {exc}")

        self._thread = threading.Thread(target=run, name="agent-listener", daemon=True)
        self._thread.start()
        logger.info(
            f"agent listener on https://{settings.agent_listener_host}:"
            f"{settings.agent_listener_port} — pin {details['fingerprint_sha256'][:16]}…"
        )
        return self.status()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._server, self._thread = None, None

    def status(self) -> dict:
        return {
            "enabled": settings.agent_listener_enabled,
            "running": self.running,
            "host": settings.agent_listener_host,
            "port": settings.agent_listener_port,
            "error": self.error,
            "certificate": agent_tls.describe(),
            # What an operator types on the target machine. Shown so nobody has to
            # guess which of the machine's addresses the agents should use.
            "addresses": [
                f"https://{addr}:{settings.agent_listener_port}"
                for addr in agent_tls.local_addresses()
                if addr not in {"127.0.0.1", "::1"}
            ],
        }


listener = AgentListener()
