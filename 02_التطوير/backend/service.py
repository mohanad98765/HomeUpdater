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
        import uvicorn

        from app.config import settings
        from app.main import app

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=settings.host,
                port=settings.port,
                log_level=settings.log_level.lower(),
            )
        )
        thread = threading.Thread(target=self._server.run, daemon=True)
        thread.start()
        win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(HomeUpdaterService)
