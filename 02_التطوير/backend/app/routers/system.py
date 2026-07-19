"""System endpoints: health, version, info, reboot."""

from __future__ import annotations

import getpass
import os
import platform
import socket
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from .. import __version__
from ..config import settings
from ..services import notifications

router = APIRouter()


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
