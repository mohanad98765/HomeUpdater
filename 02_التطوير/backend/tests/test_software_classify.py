"""winget exit-code classification.

A raw ``rc == 0`` check misreads winget's benign non-zero codes (reboot-required,
"update not applicable") as install failures, so an installed/already-current
package is persisted is_installed=False and reappears as "pending" forever.
These lock the classifier + its wiring into the install result.
"""

from __future__ import annotations

import asyncio

from app.services import software_updates as su

# 0x8A15002B = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE. Windows may hand the
# exit code back either as the unsigned DWORD or its signed int32 form.
_NOOP_UNSIGNED = 0x8A15002B
_NOOP_SIGNED = -1978335189


def test_as_dword_normalises_signed_and_unsigned():
    assert su._as_dword(0) == 0
    assert su._as_dword(_NOOP_UNSIGNED) == 0x8A15002B
    assert su._as_dword(_NOOP_SIGNED) == 0x8A15002B  # signed form maps to the same DWORD
    assert su._as_dword(-1) == 0xFFFFFFFF


def test_classify_success_and_noop_codes():
    assert su._classify_winget_rc(0) == (True, False)  # plain success
    assert su._classify_winget_rc(_NOOP_UNSIGNED) == (True, False)  # nothing to apply
    assert su._classify_winget_rc(_NOOP_SIGNED) == (True, False)  # signed form, same


def test_classify_reboot_required_codes():
    assert su._classify_winget_rc(3010) == (True, True)  # ERROR_SUCCESS_REBOOT_REQUIRED
    assert su._classify_winget_rc(1641) == (True, True)  # ERROR_SUCCESS_REBOOT_INITIATED


def test_classify_genuine_failures():
    assert su._classify_winget_rc(1) == (False, False)
    assert su._classify_winget_rc(-1) == (False, False)  # 0xFFFFFFFF, a real failure
    assert su._classify_winget_rc(0x8A150044) == (False, False)  # some other winget error


def _fake_run(rc: int):
    async def _run(*_args, **_kwargs):
        return rc, "", ""

    return _run


def test_install_result_marks_noop_as_succeeded(monkeypatch):
    # A package that is already current returns UPDATE_NOT_APPLICABLE — it must
    # NOT be recorded as a failure (the bug that left it permanently "pending").
    monkeypatch.setattr(su, "_ensure_windows", lambda: None)
    monkeypatch.setattr(su, "_run", _fake_run(_NOOP_SIGNED))
    result = asyncio.run(su.install_software_update("Some.Package"))
    assert result["succeeded"] is True
    assert result["reboot_required"] is False


def test_install_result_flags_reboot_required(monkeypatch):
    monkeypatch.setattr(su, "_ensure_windows", lambda: None)
    monkeypatch.setattr(su, "_run", _fake_run(3010))
    result = asyncio.run(su.install_software_update("Some.Package"))
    assert result["succeeded"] is True
    assert result["reboot_required"] is True


def test_install_result_genuine_failure(monkeypatch):
    monkeypatch.setattr(su, "_ensure_windows", lambda: None)
    monkeypatch.setattr(su, "_run", _fake_run(1))
    result = asyncio.run(su.install_software_update("Some.Package"))
    assert result["succeeded"] is False
    assert result["reboot_required"] is False


def test_install_many_aggregates_success_and_reboot(monkeypatch):
    async def fake_one(package_id: str):
        table = {
            "Ok.Pkg": {"succeeded": True, "reboot_required": False},
            "Reboot.Pkg": {"succeeded": True, "reboot_required": True},
            "Bad.Pkg": {"succeeded": False, "reboot_required": False},
        }
        base = {"package_id": package_id, "exit_code": 0, "stdout_tail": "", "stderr_tail": ""}
        return {**base, **table[package_id]}

    monkeypatch.setattr(su, "install_software_update", fake_one)
    result = asyncio.run(su.install_many(["Ok.Pkg", "Reboot.Pkg", "Bad.Pkg"]))
    assert result["installed"] == 2  # ok + reboot count as installed, bad does not
    assert result["total"] == 3
    assert result["reboot_required"] is True
