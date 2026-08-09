"""System endpoints: health, version, info, reboot."""

from __future__ import annotations

import getpass
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..config import settings
from ..db import get_db
from ..services import audit, cve, notifications, self_update

router = APIRouter()

# T4 self-update: check GitHub Releases for a newer signed build. We only NOTIFY
# and link to the signed installer — we never silently download+run an elevated
# installer (that would train users to bypass SmartScreen, the exact protection
# a spoofed installer relies on). Cached 1h; fails soft (checked=False) offline.
_LATEST_RELEASE_API = "https://api.github.com/repos/mohanad98765/HomeUpdater/releases/latest"
_update_cache: dict = {"at": 0.0, "data": None}


def _ver_tuple(v: str) -> tuple[int, ...]:
    parts = [int("".join(c for c in p if c.isdigit()) or 0) for p in str(v).split(".")]
    return tuple(parts) or (0,)


@router.post("/notify-test")
async def notify_test() -> dict:
    """Fire a sample desktop notification — used to verify the tray toast.

    Returns sent=True only when a tray sink handled it (i.e. running as the tray
    app); otherwise it is logged and sent=False.
    """
    sent = notifications.notify("HomeUpdater — محدِّث المنزل", "اختبار الإشعارات — تعمل بنجاح ✓")
    return {"sent": sent}


# ===================================================================
# Healthcheck / version / info
# ===================================================================
@router.get("/health")
async def health():
    """Healthcheck - used by frontend and monitoring."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": __version__,
        "build_mode": settings.build_mode,
    }


@router.get("/version")
async def version():
    """Returns the current backend version (for self-update checks)."""
    return {
        "app": settings.app_name,
        "version": __version__,
        "build": settings.build_mode,
        "app_name_ar": settings.app_name_ar,
    }


@router.get("/update-check")
async def update_check() -> dict:
    """Is a newer signed release available? Notify + link only — never auto-run.

    Read-only call to the public GitHub Releases API, cached for an hour and
    fail-soft: offline or on any error it returns ``checked=False`` so the UI
    simply doesn't nag."""
    now = time.monotonic()
    cached = _update_cache["data"]
    if cached is not None and now - _update_cache["at"] < 3600:
        return cached

    result = {
        "current": __version__,
        "latest": None,
        "update_available": False,
        "url": None,
        "checked": True,
        # Why it failed, in one short phrase. A check that fails silently is
        # indistinguishable from a check that found nothing, and the user waits forever
        # for a banner that is never coming.
        "error": "",
    }
    try:
        timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                _LATEST_RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "HomeUpdater"},
            )
        resp.raise_for_status()
        data = resp.json()
        _update_cache["release"] = data
        latest = str(data.get("tag_name", "")).lstrip("vV")
        result["latest"] = latest
        result["url"] = data.get("html_url")
        result["update_available"] = bool(latest) and _ver_tuple(latest) > _ver_tuple(__version__)
    except Exception as exc:  # noqa: BLE001 — never let a self-update check break the app
        logger.warning(f"update-check failed: {exc}")
        result["checked"] = False
        result["error"] = _why(exc)

    _update_cache["at"] = now
    _update_cache["data"] = result
    return result


def _why(exc: Exception) -> str:
    """A cause a non-technical reader can act on, not a stack trace."""
    if isinstance(exc, httpx.TimeoutException):
        return "انتهت المهلة — تحقّق من الاتّصال بالإنترنت"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (403, 429):
            return "تجاوزنا حدّ الطلبات المسموح مؤقّتًا — أعد المحاولة لاحقًا"
        return f"استجابة غير متوقّعة من الخادم ({exc.response.status_code})"
    if isinstance(exc, httpx.HTTPError):
        return "تعذّر الوصول إلى الإنترنت"
    return "تعذّر التحقّق"


# T4 delivery: the check above only ever produced a link, so every upgrade meant leaving
# the app, finding an asset on a web page, and running an installer past SmartScreen.
# These two endpoints do the fetching, and refuse anything not signed by the same
# publisher as the running build. Nothing installs without the operator pressing install.
@router.post("/update/download")
async def update_download() -> dict:
    """Download the newest release's installer and verify its publisher."""
    check = await update_check()
    if not check["checked"]:
        raise HTTPException(status_code=503, detail=check["error"] or "تعذّر التحقّق")
    if not check["update_available"]:
        raise HTTPException(status_code=409, detail="لا يوجد إصدار أحدث.")

    release = _update_cache.get("release") or {}
    try:
        running = self_update.running_installer_signature()
        asset = self_update.pick_asset(release)
        path = await self_update.download(
            asset["browser_download_url"], int(asset.get("size") or 0)
        )
        sig = self_update.verify_same_publisher(path, running)
    except self_update.SelfUpdateError as exc:
        logger.warning(f"self-update download refused: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _update_cache["installer"] = str(path)
    return {
        "ready": True,
        "version": check["latest"],
        "path": str(path),
        "publisher": sig.subject,
        "size_mb": round(int(asset.get("size") or 0) / (1024 * 1024), 1),
    }


@router.post("/update/install")
async def update_install() -> dict:
    """Run the already-verified installer. The operator asked for this explicitly, and
    Windows still shows its own elevation prompt."""
    path = _update_cache.get("installer")
    if not path:
        raise HTTPException(status_code=409, detail="لم يُنزَّل تحديث بعد.")
    try:
        self_update.launch(Path(path))
    except self_update.SelfUpdateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(f"self-update installer launched: {path}")
    return {"launched": True}


@router.get("/upgrade-notice")
async def upgrade_notice() -> dict:
    """Was the app upgraded since the previous run? Read once by the UI on load.

    Populated at startup by services/version_state: ``{upgraded, previous,
    current}``. ``upgraded`` is True only when the persisted last-seen version is
    older than the current build — i.e. the signed installer replaced files and
    relaunched. The UI shows the "upgraded from X to Y" toast once, then
    suppresses it locally.
    """
    from ..services import version_state

    return version_state.get_notice()


class SettingsUpdate(BaseModel):
    """Partial update of the user-editable settings (all optional)."""

    scan_method: Literal["auto", "python", "nmap"] | None = None
    scan_scheduler_enabled: bool | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    # NVD API keys are 36-char UUIDs; empty string is allowed and means "remove it".
    nvd_api_key: str | None = Field(default=None, max_length=100)


def _current_settings() -> dict:
    return {
        "scan_method": settings.scan_method,
        "scan_scheduler_enabled": settings.scan_scheduler_enabled,
        "scan_interval_minutes": settings.scan_interval_minutes,
        # The key itself is never returned — only whether one is set, and the pacing it
        # buys. Echoing a secret back to any local caller would undo storing it safely.
        "nvd_api_key_set": bool((settings.nvd_api_key or "").strip()),
        "nvd_min_seconds_between_calls": cve.keyed_floor(),
    }


@router.get("/settings")
async def get_settings() -> dict:
    """The user-editable settings shown on the in-app Settings page."""
    return _current_settings()


@router.post("/settings")
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Persist changed settings (whitelisted) + apply them live. If the scan
    scheduler toggle or interval changed, restart the scheduler so it takes
    effect immediately."""
    from ..config import save_settings

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    applied = save_settings(updates)
    # A settings change is an audit event: an auditor asks what the configuration
    # was at the time of a finding, and when it last changed.
    if applied:
        await audit.record_safe(
            db,
            "settings_change",
            actor="user",
            target="app-settings",
            # audit._strip_secrets() also redacts api_key, but do not even hand it over
            detail={k: ("[set]" if k == "nvd_api_key" and v else v) for k, v in applied.items()},
        )
    if "scan_scheduler_enabled" in applied or "scan_interval_minutes" in applied:
        from ..services import scheduler

        scheduler.stop()
        scheduler.start()  # idempotent + no-op when disabled
    return {**_current_settings(), "applied": sorted(applied)}


@router.get("/info")
async def system_info():
    """System info - used by frontend to show 'This computer' identity."""
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = ""
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    return {
        "version": __version__,
        "build_mode": settings.build_mode,
        "hostname": hostname,
        "user": user,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


# ===================================================================
# Reboot
# ===================================================================
class RebootRequest(BaseModel):
    """Optional confirmation for POST /reboot."""

    delay_seconds: int = Field(default=60, ge=5, le=600)
    cancel: bool = False


@router.post("/reboot")
async def reboot(req: RebootRequest = RebootRequest()) -> dict:
    """
    Schedule (or cancel) a Windows reboot.

    Default: shutdown /r /t 60 -> system reboots in 60s with a notice;
    user can cancel from this endpoint by sending {"cancel": true}.
    """
    if os.name != "nt":
        raise HTTPException(status_code=400, detail="Reboot is only supported on Windows")

    try:
        if req.cancel:
            # Abort any pending shutdown
            logger.info("POST /api/system/reboot - cancelling pending shutdown")
            subprocess.run(
                ["shutdown", "/a"],
                stdin=subprocess.DEVNULL,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {"status": "cancelled", "message": "Pending reboot cancelled (if any)"}

        delay = int(req.delay_seconds)
        msg = (
            f"HomeUpdater is rebooting this PC in {delay} seconds "
            "to finish installing Windows updates."
        )
        logger.info(f"POST /api/system/reboot - scheduling reboot in {delay}s")
        subprocess.run(
            ["shutdown", "/r", "/t", str(delay), "/c", msg],
            stdin=subprocess.DEVNULL,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "status": "scheduled",
            "delay_seconds": delay,
            "message": f"Reboot scheduled in {delay} seconds",
        }
    except subprocess.CalledProcessError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"shutdown command failed: {exc.stderr or exc.stdout or exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Reboot scheduling failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
