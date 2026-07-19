"""
Production launcher for the bundled HomeUpdater backend.

This is the PyInstaller entry point. Unlike `run.bat` (which starts the Vite dev
server separately), the packaged app is a single process: the backend serves the
built frontend from "/" and the API from "/api/*". On start it opens the browser.
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


def main() -> None:
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
    )


if __name__ == "__main__":
    main()
