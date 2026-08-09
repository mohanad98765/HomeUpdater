"""Fetch a newer HomeUpdater build and prove it came from us before running it.

The check for a newer version already existed and only ever produced a link; the user
then left the app, found the asset on a web page, downloaded 43 MB, cleared SmartScreen
and ran it as administrator. Anyone who did not finish that chain stayed on the old build
forever — which is what "the update never reaches the other machines" meant.

Delivering it is easy. Delivering it *without teaching the user to run whatever an app
hands them* is the part that needs care, so the rule here is:

    the installer we are about to run must be signed by the SAME publisher as the
    HomeUpdater that is already running, or we refuse and delete it.

That comparison is what makes this safe while the project still signs with a self-signed
certificate. A CA-issued signature would be checked by Windows itself; a self-signed one
is only meaningful as "the same key as the build you already chose to trust". We compare
the signer's certificate thumbprint, not its name — a name can be typed by anyone.

We never bypass SmartScreen and never install silently: the file is verified, then the
operator clicks, then Windows shows its own elevation prompt.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

# A release asset is ~45 MB. The cap is a defence against a redirect to something huge,
# not a size assertion — a genuine build that outgrows it fails loudly rather than filling
# the disk.
MAX_ASSET_BYTES = 200 * 1024 * 1024
ASSET_RE = re.compile(r"^HomeUpdater-Setup-\d+\.\d+\.\d+\.exe$")


class SelfUpdateError(RuntimeError):
    """Something is wrong with the download or with what it is signed by."""


@dataclass
class Signature:
    status: str
    thumbprint: str
    subject: str

    @property
    def signed(self) -> bool:
        return bool(self.thumbprint)


def _powershell(script: str, timeout: float = 60.0) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,  # windowed builds have no valid stdin handle
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="ignore",
    )
    if proc.returncode != 0:
        raise SelfUpdateError(f"powershell failed: {(proc.stderr or '').strip()[:200]}")
    return proc.stdout.strip()


def authenticode(path: Path) -> Signature:
    """Read a file's Authenticode signer. Never raises on an unsigned file — that is an
    answer, not an error."""
    out = _powershell(
        "$s = Get-AuthenticodeSignature -LiteralPath "
        f"'{path}'; "
        "Write-Output $s.Status; "
        "Write-Output $s.SignerCertificate.Thumbprint; "
        "Write-Output $s.SignerCertificate.Subject"
    )
    lines = (out.splitlines() + ["", "", ""])[:3]
    return Signature(status=lines[0].strip(), thumbprint=lines[1].strip(), subject=lines[2].strip())


def running_installer_signature() -> Signature:
    """The signature of the HomeUpdater that is running right now.

    Only meaningful in a frozen build: from a source checkout there is no signed
    executable to compare against, and pretending otherwise would make the check pass
    vacuously — the one failure mode that must not exist here.
    """
    exe = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        raise SelfUpdateError(
            "التحديث الذاتيّ متاح في النسخة المثبَّتة فقط — لا يوجد ملفّ موقَّع لمقارنته."
        )
    return authenticode(exe)


def pick_asset(release: dict) -> dict:
    """The signed installer in a GitHub release payload."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name", ""))
        if ASSET_RE.match(name) and asset.get("browser_download_url", "").startswith("https://"):
            return asset
    raise SelfUpdateError("لا يوجد ملفّ تثبيت موقَّع في هذا الإصدار.")


async def download(url: str, expected_size: int, dest_dir: Path | None = None) -> Path:
    """Download the asset to a private temp directory and return the path."""
    dest_dir = dest_dir or Path(tempfile.mkdtemp(prefix="homeupdater-update-"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "HomeUpdater-Setup.exe"

    digest = hashlib.sha256()
    written = 0
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"User-Agent": "HomeUpdater"}) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=1 << 16):
                        written += len(chunk)
                        if written > MAX_ASSET_BYTES:
                            raise SelfUpdateError("حجم الملفّ تجاوز الحدّ المسموح — أُلغي التنزيل.")
                        digest.update(chunk)
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise SelfUpdateError(f"تعذّر تنزيل التحديث: {exc}") from exc

    if expected_size and written != expected_size:
        dest.unlink(missing_ok=True)
        raise SelfUpdateError(
            f"الملفّ المنزَّل غير مكتمل ({written} بايت بدل {expected_size}) — أُلغي."
        )
    logger.info(f"update downloaded: {written} bytes, sha256 {digest.hexdigest()[:16]}…")
    return dest


def verify_same_publisher(candidate: Path, running: Signature) -> Signature:
    """Refuse anything not signed by the key that signed the running build.

    Deleting the file on refusal is deliberate: a rejected installer sitting in a temp
    folder is exactly the thing a confused user double-clicks later.
    """
    sig = authenticode(candidate)
    if not sig.signed:
        candidate.unlink(missing_ok=True)
        raise SelfUpdateError("الملفّ المنزَّل غير موقَّع — رُفض وحُذف.")
    if not running.signed:
        candidate.unlink(missing_ok=True)
        raise SelfUpdateError("النسخة المثبَّتة غير موقَّعة، فلا يمكن التحقّق من مطابقة الناشر.")
    if sig.thumbprint.upper() != running.thumbprint.upper():
        candidate.unlink(missing_ok=True)
        logger.warning(
            f"self-update REFUSED: signer {sig.thumbprint[:16]}… != running "
            f"{running.thumbprint[:16]}…"
        )
        raise SelfUpdateError("توقيع الملفّ لا يطابق توقيع النسخة المثبَّتة — رُفض وحُذف.")
    logger.info(f"self-update verified: same publisher ({sig.subject[:60]})")
    return sig


def launch(installer: Path) -> None:
    """Hand the verified installer to Windows. Windows shows its own elevation prompt;
    we do not suppress it and do not pass a silent flag."""
    if not installer.is_file():
        raise SelfUpdateError("ملفّ التثبيت لم يعد موجودًا.")
    try:
        os.startfile(str(installer))  # noqa: S606 — a verified, same-publisher installer
    except OSError as exc:
        raise SelfUpdateError(f"تعذّر تشغيل ملفّ التثبيت: {exc}") from exc
