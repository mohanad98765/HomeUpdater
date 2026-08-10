r"""An elevated process must not find its tools through a path anyone can rewrite.

The shipped exe carries a requireAdministrator manifest, and on agent machines a
scheduled task fires it every 15 minutes with nobody watching. Spawning ``winget`` by
bare name resolves through the inherited PATH — which the unprivileged user can rewrite
via HKCU\Environment\Path — and winget.exe is NOT in System32, so nothing shadows a
planted copy the way it does for schtasks or arp.

Reproduced during an audit: a decoy winget.exe placed earlier on PATH was executed by
this module, and list_installed_software() then returned "0 items, degraded=False" — a
clean, empty inventory, which is what a licence-gated Evidence Pack is built from.

The remote path already knew the answer: winrm_hosts.py locates winget.exe on the target
instead of trusting its PATH. These tests hold the local path to the same rule.
"""

from __future__ import annotations

from pathlib import Path

from app.services import software_updates as su


def _reset():
    su._WINGET_CACHE = None


def test_it_prefers_the_real_binary_over_anything_on_path(tmp_path, monkeypatch):
    _reset()
    real = tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert su.winget_path() == str(real)
    _reset()


def test_it_falls_back_to_program_files_when_the_user_copy_is_absent(tmp_path, monkeypatch):
    _reset()
    pf = tmp_path / "pf"
    target = pf / "WindowsApps" / "Microsoft.DesktopAppInstaller_1.2.3_x64__8wekyb3d8bbwe"
    target.mkdir(parents=True)
    (target / "winget.exe").write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    monkeypatch.setenv("ProgramW6432", str(pf))
    assert su.winget_path() == str(target / "winget.exe")
    _reset()


def test_a_machine_with_winget_somewhere_unusual_still_works(tmp_path, monkeypatch):
    """The guard must not brick a working machine: if the binary is genuinely not in
    either standard place, the bare name is better than refusing to run at all."""
    _reset()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nope"))
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "nope2"))
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert su.winget_path() == "winget"
    _reset()


def test_every_spawn_goes_through_the_resolver():
    """A single forgotten call site reopens the hole, and it is one word long."""
    source = Path("app/services/software_updates.py").read_text(encoding="utf-8")
    body = source.split("def winget_path", 1)[1]
    assert '_run(\n        "winget"' not in body
    assert '_run(\n            "winget"' not in body
    assert body.count("winget_path()") >= 3, "all three winget spawns must resolve first"


def test_the_resolution_is_cached_not_re_walked(tmp_path, monkeypatch):
    _reset()
    real = tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    first = su.winget_path()
    real.unlink()  # gone from disk; the answer must not change mid-session
    assert su.winget_path() == first
    _reset()
