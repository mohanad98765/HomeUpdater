"""Tests for the WinRM remote-Windows-update service (Phase 1.6).

We test the pure parsing/mapping helpers directly, and the async probe/check/
apply flows with the WinRM transport (`_run_ps`) monkeypatched — so no real
remote host or WinRM stack is needed.
"""

from __future__ import annotations

import pytest

from app.services import winrm_hosts as winrm
from tests.conftest import CSRF_HEADER


# ----------------------------------------------------------------- parse_probe
def test_parse_probe_full():
    out = "CAPTION=Microsoft Windows 11 Pro\nVERSION=10.0.26100\nHOSTNAME=DESK-1\nWINGET=True\n"
    info = winrm.parse_probe(out)
    assert info == {
        "os_name": "Microsoft Windows 11 Pro",
        "os_version": "10.0.26100",
        "hostname": "DESK-1",
        "has_winget": True,
    }


def test_parse_probe_no_winget_and_defaults():
    info = winrm.parse_probe("HOSTNAME=PC2\nWINGET=False")
    assert info["os_name"] == "Windows"  # default when CAPTION missing
    assert info["hostname"] == "PC2"
    assert info["has_winget"] is False


# ------------------------------------------------------------ winget mapping
def test_packages_from_winget_english_table():
    table = (
        "Name                 Id                     Version   Available Source\n"
        "-----------------------------------------------------------------------\n"
        "Mozilla Firefox      Mozilla.Firefox        120.0     121.0     winget\n"
        "7-Zip                7zip.7zip              23.00     24.00     winget\n"
    )
    pkgs = winrm._packages_from_winget(table)
    ids = {p["id"] for p in pkgs}
    assert ids == {"Mozilla.Firefox", "7zip.7zip"}
    ff = next(p for p in pkgs if p["id"] == "Mozilla.Firefox")
    assert ff == {
        "name": "Mozilla Firefox",
        "id": "Mozilla.Firefox",
        "current": "120.0",
        "available": "121.0",
    }


def test_packages_from_winget_empty():
    assert winrm._packages_from_winget("No installed package found matching input criteria.") == []


# ------------------------------------------------------------ friendly errors
def test_friendly_error_auth():
    class InvalidCredentialsError(Exception):
        pass

    msg = winrm._friendly_error(InvalidCredentialsError("401"))
    assert "المصادقة" in msg


def test_friendly_error_connection():
    err = ConnectionError("Max retries exceeded: actively refused")
    msg = winrm._friendly_error(err)
    assert "WinRM" in msg and "المنفذ" in msg


# --------------------------------------------------------------- probe flow
async def test_probe_success(monkeypatch):
    async def fake_run_ps(host, port, user, pw, https, transport, script, verify_tls=False):
        assert script == winrm._PROBE_PS
        return 0, "CAPTION=Windows 11\nVERSION=10.0.26100\nHOSTNAME=H1\nWINGET=True\n", ""

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    info = await winrm.probe("10.0.0.5", 5985, "admin", "pw")
    assert info["hostname"] == "H1"
    assert info["has_winget"] is True


async def test_probe_empty_output_raises(monkeypatch):
    async def fake_run_ps(*a, **k):
        return 1, "", "Access is denied."

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    with pytest.raises(winrm.WinRMHostError):
        await winrm.probe("10.0.0.5", 5985, "admin", "bad")


# --------------------------------------------------------------- check flow
async def test_check_updates_parses_table(monkeypatch):
    table = (
        "Name        Id               Version  Available Source\n"
        "----------------------------------------------------------\n"
        "VLC         VideoLAN.VLC     3.0.18   3.0.20    winget\n"
    )

    async def fake_run_ps(*a, **k):
        return 0, table, ""

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    result = await winrm.check_updates("10.0.0.5", 5985, "admin", "pw")
    assert result["total"] == 1
    assert result["packages"][0]["id"] == "VideoLAN.VLC"


async def test_check_updates_winget_missing_raises(monkeypatch):
    async def fake_run_ps(*a, **k):
        return 3, "WINGET_NOT_FOUND\n", ""

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    with pytest.raises(winrm.WinRMHostError):
        await winrm.check_updates("10.0.0.5", 5985, "admin", "pw")


async def test_check_updates_command_failure_raises(monkeypatch):
    """Non-zero rc with no output = failed check, not 'up to date'."""

    async def fake_run_ps(*a, **k):
        return 1, "", "0x8a15000f : The source cdn is not accessible."

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    with pytest.raises(winrm.WinRMHostError):
        await winrm.check_updates("10.0.0.5", 5985, "admin", "pw")


async def test_check_updates_nonzero_rc_with_table_ok(monkeypatch):
    """winget often exits non-zero (reboot pending) yet still lists packages."""
    table = (
        "Name  Id            Version Available Source\n"
        "-------------------------------------------------\n"
        "VLC   VideoLAN.VLC  3.0.18  3.0.20    winget\n"
    )

    async def fake_run_ps(*a, **k):
        return 1, table, "reboot required"

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    result = await winrm.check_updates("10.0.0.5", 5985, "admin", "pw")
    assert result["total"] == 1


# --------------------------------------------------------------- apply flow
async def test_apply_updates_reports_exit(monkeypatch):
    async def fake_run_ps(*a, **k):
        return 0, "Successfully installed", ""

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    result = await winrm.apply_updates("10.0.0.5", 5985, "admin", "pw")
    assert result["succeeded"] is True
    assert result["exit_status"] == 0


async def test_apply_updates_winget_missing_raises(monkeypatch):
    async def fake_run_ps(*a, **k):
        return 3, "WINGET_NOT_FOUND", ""

    monkeypatch.setattr(winrm, "_run_ps", fake_run_ps)
    with pytest.raises(winrm.WinRMHostError):
        await winrm.apply_updates("10.0.0.5", 5985, "admin", "pw")


# --------------------------------------------------------------- TLS validation
def test_verify_tls_selects_cert_validation(monkeypatch):
    """Over HTTPS, verify_tls=True validates the cert; otherwise it's ignored."""
    import winrm as winrm_mod

    captured: dict = {}

    class _Result:
        status_code = 0
        std_out = b"CAPTION=Windows 11\n"
        std_err = b""

    class _FakeSession:
        def __init__(self, endpoint, **kw):
            captured.clear()
            captured.update(kw)

        def run_ps(self, script):
            return _Result()

    monkeypatch.setattr(winrm_mod, "Session", _FakeSession)

    winrm._run_ps_sync("h", 5986, "u", "p", True, "basic", "echo", verify_tls=True)
    assert captured["server_cert_validation"] == "validate"

    winrm._run_ps_sync("h", 5986, "u", "p", True, "ntlm", "echo", verify_tls=False)
    assert captured["server_cert_validation"] == "ignore"

    # verify_tls only applies over HTTPS; plain HTTP is always "ignore".
    winrm._run_ps_sync("h", 5985, "u", "p", False, "ntlm", "echo", verify_tls=True)
    assert captured["server_cert_validation"] == "ignore"


# --------------------------------------------------------------- endpoint smoke
def test_winrm_hosts_list_empty(client):
    """The /api/winrm/hosts endpoint returns an empty list on a fresh DB."""
    body = client.get("/api/winrm/hosts").json()
    assert body == {"hosts": [], "total": 0}


def test_add_host_verifies_and_hides_password(client, monkeypatch):
    async def fake_probe(
        host, port, username, password, use_https=False, transport="ntlm", verify_tls=False
    ):
        return {
            "os_name": "Windows 11 Pro",
            "os_version": "10.0.26100",
            "hostname": "DESK-1",
            "has_winget": True,
        }

    monkeypatch.setattr(winrm, "probe", fake_probe)
    r = client.post(
        "/api/winrm/hosts",
        json={"host": "10.0.0.7", "username": "Admin", "password": "secret"},
        headers=CSRF_HEADER,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["hostname"] == "DESK-1"
    assert body["has_winget"] is True
    assert body["has_password"] is True
    assert "password" not in body
    assert client.get("/api/winrm/hosts").json()["total"] == 1


def test_basic_over_http_rejected(client):
    """basic auth over plain HTTP would send the password near-cleartext."""
    r = client.post(
        "/api/winrm/hosts",
        json={
            "host": "10.0.0.8",
            "username": "Admin",
            "password": "pw",
            "transport": "basic",
            "use_https": False,
        },
        headers=CSRF_HEADER,
    )
    assert r.status_code == 400
