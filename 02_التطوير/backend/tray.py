"""
System-tray launcher for HomeUpdater.

Runs the backend (uvicorn) in a background thread and shows a Windows tray icon
with a right-click menu (Open / API docs / Quit). This is the production GUI
entry point — a real background app instead of a console window. On start it
opens the browser (skip with HOMEUPDATER_NO_BROWSER).
"""

from __future__ import annotations

import os
import threading
import webbrowser


def _ensure_std_streams() -> None:
    """In a windowed (--noconsole) build, sys.stdout/stderr are None. Give them a
    discard sink so libraries that touch them (uvicorn's log formatter calls
    sys.stdout.isatty(), plus print/loguru) don't crash the whole app."""
    import sys

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))  # noqa: SIM115


def _close_splash() -> None:
    """Close the PyInstaller startup splash (only present in the --splash build)."""
    try:
        import pyi_splash

        pyi_splash.close()
    except Exception:
        pass


def _make_icon_image():
    """The brand tray icon (assets/tray.png, bundled by PyInstaller).

    Falls back to a drawn house mark if the asset is missing.
    """
    import sys
    from pathlib import Path

    from PIL import Image, ImageDraw

    base = getattr(sys, "_MEIPASS", None) or str(Path(__file__).resolve().parent)
    icon_path = Path(base) / "assets" / "tray.png"
    if icon_path.is_file():
        return Image.open(icon_path)

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([6, 6, 58, 58], radius=14, fill=(13, 71, 161, 255))  # #0D47A1
    draw.polygon([(32, 18), (16, 32), (48, 32)], fill=(255, 255, 255, 255))
    draw.rectangle([22, 30, 42, 48], fill=(255, 255, 255, 255))
    return img


class _BackgroundServer:
    """uvicorn running in a daemon thread, stoppable from the tray."""

    def __init__(self, host: str, port: int, log_level: str):
        import uvicorn

        from app.main import app

        # log_config=None: skip uvicorn's own logging setup (its color formatter
        # calls sys.stdout.isatty(), which crashes in a windowed build). The app
        # configures loguru itself in the lifespan.
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level=log_level, log_config=None)
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True


def main() -> None:
    _ensure_std_streams()  # must run before uvicorn/loguru touch the streams

    import pystray

    from app.config import find_free_port, settings
    from app.services import notifications

    # Move to the next free port if the default is taken, so the app still loads.
    port = find_free_port(settings.port, settings.host)
    ui_host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    url = f"http://{ui_host}:{port}/"
    server = _BackgroundServer(settings.host, port, settings.log_level.lower())
    server.start()

    def _open(*_):
        webbrowser.open(url)

    def _open_docs(*_):
        webbrowser.open(url + "docs")

    def _quit(icon, _item):
        server.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("افتح HomeUpdater / Open", _open, default=True),
        pystray.MenuItem("التوثيق / API docs", _open_docs),
        pystray.MenuItem("خروج / Quit", _quit),
    )
    icon = pystray.Icon("HomeUpdater", _make_icon_image(), "HomeUpdater — محدِّث المنزل", menu)

    def _on_ready(ic):
        # Once the tray loop is running, route backend notifications to toasts.
        notifications.set_sink(lambda title, message: ic.notify(message, title))

    def _wait_ready_then_open():
        # Keep the startup splash visible until the server accepts connections,
        # then close it and open the browser — so the UI is live when it appears.
        import socket
        import time

        for _ in range(80):  # up to ~8s
            try:
                with socket.create_connection((ui_host, port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        _close_splash()
        if not os.environ.get("HOMEUPDATER_NO_BROWSER"):
            webbrowser.open(url)

    threading.Thread(target=_wait_ready_then_open, daemon=True).start()
    icon.run(setup=_on_ready)


if __name__ == "__main__":
    main()
