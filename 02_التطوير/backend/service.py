"""
Windows Service wrapper (pywin32) for the HomeUpdater backend.

Runs uvicorn headless so the hub keeps working without an interactive login.
Must be run elevated:

    python service.py install     # register the service
    python service.py start       # start it
    python service.py stop        # stop it
    python service.py remove      # unregister it

When frozen, PyInstaller produces a service exe; install it the same way with
the built executable instead of `python service.py`.
"""

from __future__ import annotations

import threading

import servicemanager
import win32event
import win32service
import win32serviceutil


class HomeUpdaterService(win32serviceutil.ServiceFramework):
    _svc_name_ = "HomeUpdater"
    _svc_display_name_ = "HomeUpdater — محدِّث المنزل"
    _svc_description_ = "Local home-network device update hub (backend API + UI)."

    def __init__(self, args):
        super().__init__(args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._server is not None:
            self._server.should_exit = True
        win32event.SetEvent(self._stop_event)

    def SvcDoRun(self):
        import os
        import sys

        # A service has no console: sys.stdout/stderr are None. Guard them so
        # uvicorn's log formatter (sys.stdout.isatty()) doesn't crash.
        for name in ("stdout", "stderr"):
            if getattr(sys, name) is None:
                setattr(sys, name, open(os.devnull, "w"))  # noqa: SIM115

        import uvicorn

        from app.config import find_free_port, settings
        from app.main import app

        # Don't bind a busy port (which would leave the service reporting RUNNING
        # while listening on nothing) — move to the next free one, like the GUI.
        port = find_free_port(settings.port, settings.host)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, f" on port {port}"),
        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=settings.host,
                port=port,
                log_level=settings.log_level.lower(),
                log_config=None,
            )
        )

        def _serve():
            try:
                self._server.run()
            except Exception as exc:  # surface bind/startup failures to the Event Log
                servicemanager.LogErrorMsg(f"HomeUpdater service failed: {exc}")
                win32event.SetEvent(self._stop_event)

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(HomeUpdaterService)
