"""Self-update: the download is easy, refusing the wrong file is the feature.

The app can now fetch a new build and run it. That is one step away from teaching a user
to run whatever an application hands them, so the tests here are about the refusals — a
guard that has never been made to fire is not a guard.

The publisher check was also measured against three real files on the developer machine
(the signed HomeUpdater build, a Microsoft-signed system binary, and an unsigned file).
The Microsoft binary is the interesting one: Windows reports its signature as *Valid*,
and it is still refused, because "validly signed" is not the property that matters —
"signed by the same key as the build already installed" is.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import self_update
from app.services.self_update import Signature

OURS = Signature(status="Valid", thumbprint="AABBCC112233", subject="CN=HomeUpdater")
THEIRS = Signature(status="Valid", thumbprint="998877ZZZZZZ", subject="CN=Someone Else")
UNSIGNED = Signature(status="NotSigned", thumbprint="", subject="")


def _file(tmp_path: Path) -> Path:
    p = tmp_path / "HomeUpdater-Setup.exe"
    p.write_bytes(b"MZ" + b"\0" * 128)
    return p


def test_the_same_publisher_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update, "authenticode", lambda _p: OURS)
    got = self_update.verify_same_publisher(_file(tmp_path), OURS)
    assert got.thumbprint == OURS.thumbprint


def test_a_validly_signed_file_from_someone_else_is_refused_and_deleted(tmp_path, monkeypatch):
    """Status=Valid is not the test. A Microsoft-signed binary passes Windows' own check
    and must still be refused — measured against the real notepad.exe on this machine."""
    monkeypatch.setattr(self_update, "authenticode", lambda _p: THEIRS)
    target = _file(tmp_path)
    with pytest.raises(self_update.SelfUpdateError) as exc:
        self_update.verify_same_publisher(target, OURS)
    assert "لا يطابق" in str(exc.value)
    assert not target.exists(), "a refused installer left on disk is the thing a user clicks"


def test_an_unsigned_file_is_refused_and_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update, "authenticode", lambda _p: UNSIGNED)
    target = _file(tmp_path)
    with pytest.raises(self_update.SelfUpdateError):
        self_update.verify_same_publisher(target, OURS)
    assert not target.exists()


def test_an_unsigned_RUNNING_build_cannot_vouch_for_anything(tmp_path, monkeypatch):
    """The comparison is only meaningful if the thing we compare against is itself
    signed. Otherwise "" == "" and every file passes — the one failure mode that would
    make this whole feature theatre."""
    monkeypatch.setattr(self_update, "authenticode", lambda _p: UNSIGNED)
    target = _file(tmp_path)
    with pytest.raises(self_update.SelfUpdateError):
        self_update.verify_same_publisher(target, UNSIGNED)
    assert not target.exists()


def test_running_signature_is_refused_outside_a_frozen_build(monkeypatch):
    monkeypatch.delattr("sys.frozen", raising=False)
    with pytest.raises(self_update.SelfUpdateError) as exc:
        self_update.running_installer_signature()
    assert "المثبَّتة" in str(exc.value)


# --- which asset ---------------------------------------------------------------------
def test_only_our_signed_installer_asset_is_picked():
    release = {
        "assets": [
            {"name": "source.zip", "browser_download_url": "https://x/source.zip"},
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
            {
                "name": "HomeUpdater-Setup-1.24.0.exe",
                "browser_download_url": "https://x/HomeUpdater-Setup-1.24.0.exe",
            },
        ]
    }
    assert self_update.pick_asset(release)["name"] == "HomeUpdater-Setup-1.24.0.exe"


def test_a_plain_http_asset_is_not_picked():
    """Downgrading to http would let anyone on the path swap the installer, and the
    publisher check would then be the only thing standing between them and an elevated
    run. It is not the only thing that has to hold."""
    release = {
        "assets": [
            {
                "name": "HomeUpdater-Setup-1.24.0.exe",
                "browser_download_url": "http://x/HomeUpdater-Setup-1.24.0.exe",
            }
        ]
    }
    with pytest.raises(self_update.SelfUpdateError):
        self_update.pick_asset(release)


def test_a_release_with_no_installer_says_so():
    with pytest.raises(self_update.SelfUpdateError):
        self_update.pick_asset({"assets": []})


def test_an_asset_named_like_ours_but_not_ours_is_ignored():
    release = {
        "assets": [
            {"name": "HomeUpdater-Setup.exe", "browser_download_url": "https://x/a.exe"},
            {"name": "evil-HomeUpdater-Setup-1.0.0.exe", "browser_download_url": "https://x/b"},
        ]
    }
    with pytest.raises(self_update.SelfUpdateError):
        self_update.pick_asset(release)


# --- the download --------------------------------------------------------------------
def test_a_short_download_is_rejected_rather_than_run(tmp_path, monkeypatch):
    """A truncated installer is not a smaller installer. Running one is how a machine
    ends up with a half-replaced application."""

    class _Resp:
        def raise_for_status(self):
            pass

        async def aiter_bytes(self, chunk_size=0):
            yield b"MZ" + b"\0" * 100

    class _Stream:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _Stream()

    monkeypatch.setattr(self_update.httpx, "AsyncClient", _Client)
    with pytest.raises(self_update.SelfUpdateError) as exc:
        asyncio.run(self_update.download("https://x/a.exe", 999_999, tmp_path))
    assert "غير مكتمل" in str(exc.value)
    assert not (tmp_path / "HomeUpdater-Setup.exe").exists()
