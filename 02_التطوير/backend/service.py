"""
Optional Windows Service wrapper (pywin32) for the HomeUpdater backend.

Runs uvicorn headless so the hub keeps working without an interactive login.

NOTE (see SERVICE.md): for most users the recommended "start with Windows" is the
installer's Scheduled-Task option (elevated GUI at logon, no UAC prompt), NOT this
service. If you DO want a headless service, run it **as the interactive user** and
point it at that user's data with HOMEUPDATER_DATA_DIR so the per-user DPAPI
credential key still decrypts — a LocalSystem service writes to the SYSTEM profile
and cannot read the user's encrypted secrets.

Dev usage (elevated):
    python service.py install --username .\\<you> --password <pw>   # run as you
    python service.py start / stop / remove

Frozen: the shipped HomeUpdater.exe is the GUI, not a service host. To run this as
a service from a frozen build, build a SEPARATE console exe whose entry point is
this file; the SCM then starts it through the dispatcher branch in __main__ below.
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
    import sys

    if len(sys.argv) == 1 and getattr(sys, "frozen", False):
        # Started by the Windows Service Control Manager as a frozen service exe:
        # hand control to the service dispatcher (HandleCommandLine can't do this).
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(HomeUpdaterService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # CLI: install / start / stop / remove (and dev `python service.py <cmd>`).
        win32serviceutil.HandleCommandLine(HomeUpdaterService)
