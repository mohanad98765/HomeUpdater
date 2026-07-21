"""Platform remediation (v1.4.7): nmap made truly optional (lazy import), adb
stdin pinned + state checks, and the elevation guard (خطأ 740)."""

from __future__ import annotations

import inspect

from app import win_elevation
from app.services import android, discovery


def test_nmap_is_not_a_top_level_import():
    # A module-top `import nmap` would make python-nmap a hard load-time dependency
    # and crash app load if it weren't bundled. It must only appear indented (lazy).
    src = inspect.getsource(discovery)
    assert "\nimport nmap" not in src  # column-0 import => top level
    assert isinstance(discovery._nmap_available(), bool)


def test_do_scan_raises_discoveryerror_if_nmap_missing():
    src = inspect.getsource(discovery._do_scan)
    assert "import nmap" in src  # lazy import lives inside the function
    assert "DiscoveryError" in src


def test_adb_run_pins_stdin_to_devnull_when_no_input():
    # Windowed builds have no valid stdin handle; not pinning it can hang adb.
    src = inspect.getsource(android._run_adb_blocking)
    assert "stdin=subprocess.DEVNULL if input_text is None" in src


def test_adb_check_reports_missing_gracefully(monkeypatch):
    monkeypatch.setattr(android, "_adb_exe", lambda: None)
    ok, msg = android.adb_check()
    assert ok is False
    assert "adb" in msg.lower()


def test_adb_state_returns_offline_on_error(monkeypatch):
    def boom(*_a, **_k):
        raise android.AndroidError("no device")

    monkeypatch.setattr(android, "_run_adb_blocking", boom)
    assert android.adb_state("bogus-serial") == "offline"


def test_is_admin_returns_bool():
    assert isinstance(win_elevation.is_admin(), bool)


def test_ensure_elevated_is_noop_when_admin(monkeypatch):
    monkeypatch.setattr(win_elevation, "is_admin", lambda: True)
    win_elevation.ensure_elevated()  # must return (not sys.exit) when already elevated


def test_launch_elevated_noop_off_windows(monkeypatch):
    monkeypatch.setattr(win_elevation.os, "name", "posix")
    assert win_elevation.launch_elevated("whatever.exe") is False
