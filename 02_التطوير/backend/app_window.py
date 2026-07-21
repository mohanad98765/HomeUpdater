"""
Native single-window launcher for HomeUpdater (WebView2 shell, no browser).

uvicorn runs in a background daemon thread; pywebview (WebView2 / edgechromium)
hosts the local web UI in a REAL desktop application window on the MAIN thread —
no browser, no address bar. Closing the window shuts the server down and exits.
If the WebView2 runtime is missing (or the window fails to open) it falls back to
the default browser so it is never worse than the old launcher.

This is the production GUI entry point (the PyInstaller spec points here).
`tray.py` remains as an alternate system-tray/browser entry point.

Design: single Win32 message loop (pywebview on the main thread), one uvicorn
daemon thread, a transient readiness helper. See DEVICES.md / the design notes.
"""

from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "HomeUpdater"
# Local\ (per-session) namespace: prevents a same-user double launch WITHOUT
# needing SeCreateGlobalPrivilege (which a non-elevated user lacks — a Global\
# mutex would fail with ERROR_ACCESS_DENIED and silently no-op the guard).
MUTEX_NAME = "Local\\HomeUpdater_singleton"
WEBVIEW2_DOWNLOAD = "https://developer.microsoft.com/microsoft-edge/webview2/"
# Correct WebView2 Evergreen Runtime client GUID (verified; not the common typo).
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _ensure_std_streams() -> None:
    """Windowed (--noconsole) builds have sys.stdout/stderr = None. Give them a
    discard sink so uvicorn/loguru/pythonnet don't crash on first write."""
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


def _msgbox(text: str, flags: int = 0x40) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, flags)
    except Exception:
        pass


def _single_instance_or_exit():
    """Prevent a second copy from launching a second uvicorn on the same port."""
    try:
        # use_last_error=True so ctypes.get_last_error() reads the value set by
        # CreateMutexW itself (windll.kernel32.GetLastError() can be clobbered by
        # ctypes' own bookkeeping between the two calls).
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            _msgbox(f"{APP_NAME} قيد التشغيل بالفعل / is already running.")
            raise SystemExit(0)
        return handle  # keep alive for the whole process lifetime
    except SystemExit:
        raise
    except Exception:
        return None  # mutex is best-effort; don't block startup if it fails


def _webview2_present() -> bool:
    """True if the Evergreen WebView2 Runtime is installed (per-machine or -user)."""
    import winreg

    subs = (
        (
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}",
        ),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
    )
    for root, sub in subs:
        try:
            with winreg.OpenKey(root, sub) as key:
                pv, _ = winreg.QueryValueEx(key, "pv")
                if pv and pv not in ("", "0.0.0.0"):
                    return True
        except OSError:
            continue
    return False


def _wait_for_port(host: str, port: int, timeout_s: float = 12.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class _BackgroundServer:
    """uvicorn running in a daemon thread, stoppable from the window-close event."""

    def __init__(self, host: str, port: int, log_level: str):
        import uvicorn

        from app.main import app

        # log_config=None: skip uvicorn's own logging setup (its color formatter
        # calls sys.stdout.isatty(), which crashes in a windowed build).
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level=log_level, log_config=None)
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True

    def join(self, timeout: float | None = 5.0) -> None:
        self._thread.join(timeout)


def _run_browser_fallback(
    server: _BackgroundServer, ui_host: str, port: int, real_url: str, reason: str
) -> None:
    """WebView2 missing or window failed: open the browser, keep the server up.

    A --noconsole build gets no Ctrl-C, so we must give the user a *reachable*
    way to quit: a blocking, dismissable message box acts as the exit gate.
    When it is dismissed we stop the server and return, so no orphan backend is
    left bound to the LAN port. (In no-browser/headless mode we skip the modal
    and just stop, so tests never block.)
    """
    _close_splash()  # first — the always-on-top splash would hide the modal below
    _msgbox(reason + f"\n\nWebView2:\n{WEBVIEW2_DOWNLOAD}")
    ready = _wait_for_port(ui_host, port)
    if os.environ.get("HOMEUPDATER_NO_BROWSER"):
        server.stop()
        server.join(timeout=5)
        return
    if ready:
        webbrowser.open(real_url)
    # Blocking modal = the only reachable quit signal in a windowed build.
    _msgbox(
        "HomeUpdater يعمل الآن في متصفّحك.\n"
        "عند الانتهاء، أغلق تبويب المتصفّح ثم اضغط OK لإيقاف HomeUpdater.\n\n"
        "HomeUpdater is running in your browser. When done, close the tab and "
        "click OK to stop it."
    )
    server.stop()
    server.join(timeout=5)


def main() -> None:
    _ensure_std_streams()  # MUST be first, before uvicorn/loguru/pythonnet

    # Guarantee elevation (the app updates Windows/devices). No-op in the shipped
    # exe (requireAdministrator manifest); relaunches a non-elevated source run.
    from app.win_elevation import ensure_elevated

    ensure_elevated()
    _mutex = _single_instance_or_exit()  # noqa: F841 — kept alive intentionally

    # A per-launch secret that authenticates the elevated API. Set it BEFORE the
    # config import so settings.session_token picks it up; deliver it to the UI
    # via the launch URL only (never served in the HTML).
    import secrets

    token = os.environ.get("HOMEUPDATER_SESSION_TOKEN") or secrets.token_urlsafe(32)
    os.environ["HOMEUPDATER_SESSION_TOKEN"] = token

    from app.config import find_free_port, settings

    # If the configured port is taken (a leftover/old instance, another program),
    # move to the next free one instead of failing to load.
    port = find_free_port(settings.port, settings.host)
    ui_host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    # Token in the URL *fragment* (#), not the query (?): fragments are never sent
    # to the server nor in Referer headers, so the secret never rides an HTTP
    # request or a log. The SPA reads it from location.hash and clears it.
    real_url = f"http://{ui_host}:{port}/#t={token}"

    # WebView2 user-data folder must be writable even under Program Files.
    storage = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "WebView2"
    try:
        storage.mkdir(parents=True, exist_ok=True)
    except Exception:
        storage = Path(os.environ.get("TEMP", ".")) / "HomeUpdater_WebView2"
        storage.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(storage))

    server = _BackgroundServer(settings.host, port, settings.log_level.lower())
    server.start()

    # No native tray sink in the window build; backend notifications simply no-op
    # at the OS level and remain visible inside the SPA. (tray.py keeps toasts.)

    if not _webview2_present():
        _run_browser_fallback(
            server,
            ui_host,
            port,
            real_url,
            "متصفّح WebView2 غير مثبّت — سيتم فتح الواجهة في المتصفّح.\n"
            "The WebView2 Runtime is required for the native window; "
            "opening in your browser instead.",
        )
        return

    import webview

    base = getattr(sys, "_MEIPASS", None) or str(Path(__file__).resolve().parent)
    loading = Path(base) / "loading.html"

    window = webview.create_window(
        title="HomeUpdater — محدِّث المنزل",
        url=str(loading) if loading.is_file() else None,
        html=(
            None
            if loading.is_file()
            else "<div style='font-family:Segoe UI,Tahoma,sans-serif;text-align:center;"
            "margin-top:38vh;color:#0D47A1'><h2>… جارٍ التشغيل / Starting …</h2></div>"
        ),
        width=1180,
        height=800,
        min_size=(900, 600),
        confirm_close=False,
    )

    def _on_closed():
        server.stop()  # -> uvicorn should_exit -> FastAPI lifespan shutdown

    window.events.closed += _on_closed

    def _on_started(win):
        # Runs on a pywebview worker thread once the GUI loop is live.
        try:
            if _wait_for_port(ui_host, port):
                win.load_url(real_url)
            else:
                _msgbox(
                    "تعذّر تشغيل خادم HomeUpdater.\n"
                    "HomeUpdater backend failed to start — see logs in "
                    "%LOCALAPPDATA%\\HomeUpdater\\logs."
                )
                win.destroy()
        finally:
            _close_splash()

    try:
        webview.start(
            _on_started,
            window,
            gui="edgechromium",  # never silently fall back to the ancient MSHTML/IE backend
            private_mode=False,  # persist the SPA's localStorage between runs
            storage_path=str(storage),
            debug=False,
        )
    except Exception as exc:  # runtime present but instantiation failed
        _close_splash()
        _run_browser_fallback(
            server,
            ui_host,
            port,
            real_url,
            f"تعذّر فتح النافذة الأصلية — سيتم الفتح في المتصفّح.\n"
            f"Failed to open the native window ({exc}); opening in your browser instead.",
        )
        return

    # webview.start() returned -> all windows closed -> deterministic teardown.
    server.stop()  # idempotent
    server.join(timeout=5)  # daemon thread is the hard backstop
    sys.exit(0)


if __name__ == "__main__":
    main()
