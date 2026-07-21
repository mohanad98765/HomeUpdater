"""Windows elevation helpers (خطأ 740 / ERROR_ELEVATION_REQUIRED).

The shipped exe already forces elevation via a requireAdministrator manifest
(HomeUpdater.spec: uac_admin=True), so ``ensure_elevated`` is a no-op there. It
matters for (a) running from source without the manifest and (b) launching a
child installer (self-update) that itself needs elevation — the paths where a
non-elevated launch would otherwise raise error 740. Never disables UAC.
"""

from __future__ import annotations

import ctypes
import os
import sys

_SW_SHOWNORMAL = 1


def _quote(args: list[str]) -> str:
    return " ".join(f'"{a}"' for a in args)


def is_admin() -> bool:
    """True if the current process is elevated (or not on Windows)."""
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 — treat an API failure as not-admin
        return False


def ensure_elevated() -> None:
    """If not elevated, relaunch self via the ``runas`` verb and exit; else return.

    Handles both the frozen exe and a source run (``python app_window.py``). If
    the user declines the UAC prompt we inform them and exit rather than loop.
    """
    if is_admin():
        return
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, _quote(sys.argv[1:])
    else:  # source: relaunch the interpreter WITH the script path + args
        exe, params = sys.executable, _quote(sys.argv)
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, _SW_SHOWNORMAL)
    except Exception:  # noqa: BLE001
        rc = 0
    if rc <= 32:  # <=32 == failure; 5/1223 == user declined the UAC prompt
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "يتطلّب محدِّث المنزل صلاحيات المسؤول ليُحدّث Windows والأجهزة.\n"
                "أعِد تشغيله بصلاحيات مسؤول.",
                "محدِّث المنزل — HomeUpdater",
                0x10,  # MB_ICONERROR
            )
        except Exception:  # noqa: BLE001
            pass
    sys.exit(0)  # the elevated instance (if any) takes over


def launch_elevated(path: str, args: str = "") -> bool:
    """Launch a child (e.g. the self-update installer) elevated. Returns success.

    Use this instead of a plain subprocess/ShellExecute for anything that needs
    admin — a non-elevated child launch is exactly what raises error 740."""
    if os.name != "nt":
        return False
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", path, args, None, _SW_SHOWNORMAL)
    except Exception:  # noqa: BLE001
        return False
    return rc > 32
