"""
Console/browser launcher for the bundled HomeUpdater backend (diagnostic).

NOTE: the shipped PyInstaller entry point is `app_window.py` (native window). This
console launcher is kept for troubleshooting. Unlike `run.bat` (which starts the
Vite dev server separately), the packaged app is a single process: the backend
serves the built frontend from "/" and the API from "/api/*". On start it opens
the browser.

Security: this launcher does NOT set HOMEUPDATER_SESSION_TOKEN, so the API's
session-token auth is not enforced when started this way — it is a same-user
diagnostic path only. The shipped elevated app runs through app_window.py, which
generates and enforces the token.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser


def _open_browser_later(url: str) -> None:
    time.sleep(2.0)  # give uvicorn a moment to bind
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _ensure_std_streams() -> None:
    """No-console builds have sys.stdout/stderr = None; give them a discard sink
    so uvicorn's log formatter (sys.stdout.isatty()) and print don't crash."""
    import sys

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))  # noqa: SIM115


def main() -> None:
    _ensure_std_streams()

    import uvicorn

    from app.config import settings
    from app.main import app

    url = f"http://{settings.host}:{settings.port}/"
    # Skip auto-opening the browser when run as a service or during tests.
    if not os.environ.get("HOMEUPDATER_NO_BROWSER"):
        threading.Thread(target=_open_browser_later, args=(url,), daemon=True).start()

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        log_config=None,
    )


if __name__ == "__main__":
    main()
