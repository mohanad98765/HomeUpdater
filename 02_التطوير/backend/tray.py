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


def _make_icon_image():
    """A placeholder brand icon (blue shield + update check). TODO(Phase A): swap
    for the real logo once art exists."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([10, 6, 54, 50], radius=12, fill=(13, 71, 161, 255))  # #0D47A1
    draw.line([(22, 30), (30, 39), (45, 19)], fill=(255, 255, 255, 255), width=6, joint="curve")
    return img


class _BackgroundServer:
    """uvicorn running in a daemon thread, stoppable from the tray."""

    def __init__(self, host: str, port: int, log_level: str):
        import uvicorn

        from app.main import app

        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level=log_level)
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True


def main() -> None:
    import pystray

    from app.config import settings

    url = f"http://{settings.host}:{settings.port}/"
    server = _BackgroundServer(settings.host, settings.port, settings.log_level.lower())
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

    if not os.environ.get("HOMEUPDATER_NO_BROWSER"):
        threading.Timer(2.0, _open).start()

    icon.run()


if __name__ == "__main__":
    main()
