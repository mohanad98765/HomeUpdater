"""
Updates router - Windows Update operations.

Endpoints (mounted under /api/updates):
  GET   /windows                   -> list cached pending updates
  POST  /windows/check             -> re-search Windows Update for pending items
  POST  /windows/install           -> install one or more updates by update_id
  GET   /windows/status            -> live progress of the current operation
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import SoftwarePackageORM, WindowsUpdateORM
from ..services import notifications
from ..services.software_updates import (
    SoftwareUpdateError,
    install_many,
    list_software_updates,
)
from ..services.update_progress import update_progress
from ..services.windows_updates import (
    WindowsUpdateError,
    check_for_updates,
    install_updates,
)

router = APIRouter()


def _claims_update_slot(operation: str):
    """Decorator: reserve the single update slot for the whole handler.

    Only one update operation (check/install) may run at a time — all runs share
    the `update_progress` singleton and the WUA/winget COM/subprocess pipeline,
    so overlapping runs corrupt the progress feed and race on the DB upsert. The
    claim is atomic and happens BEFORE the wrapped coroutine runs (so a second
    request can't slip through a check-then-act `await` gap), and the slot is
    always released on exit (early return, error, or normal completion).
    """

    def decorator(fn):
        @functools.wraps(fn)  # preserves the signature so FastAPI DI still works
        async def wrapper(*args, **kwargs):
            if not update_progress.try_claim(operation):
                raise HTTPException(
                    status_code=409,
                    detail="عملية تحديث أخرى قيد التنفيذ / Another update operation is running",
                )
            try:
                return await fn(*args, **kwargs)
            finally:
                update_progress.release()

        return wrapper

    return decorator


# ===================================================================
# Request schemas
# ===================================================================
class InstallRequest(BaseModel):
    """POST /windows/install body."""

    update_ids: list[str] = Field(
        default_factory=list,
        description="WUA update IDs to install. Empty = install all pending.",
    )


# ===================================================================
# GET /windows  -> list cached pending updates
# ===================================================================
@router.get("/windows")
async def list_windows_updates(db: AsyncSession = Depends(get_db)) -> dict:
    """Return cached Windows (software) updates."""
    return await _list_wua_updates(db, kind="windows")


@router.get("/drivers")
async def list_driver_updates(db: AsyncSession = Depends(get_db)) -> dict:
    """Return cached Driver updates."""
    return await _list_wua_updates(db, kind="driver")


async def _list_wua_updates(db: AsyncSession, kind: str) -> dict:
    """Shared helper: list rows of a given kind from the WUA cache."""
    result = await db.execute(
        select(WindowsUpdateORM)
        .where(WindowsUpdateORM.kind == kind)
        .order_by(WindowsUpdateORM.last_checked.desc())
    )
    rows = result.scalars().all()
    pending = [r.to_dict() for r in rows if not r.is_installed]
    installed = [r.to_dict() for r in rows if r.is_installed]
    total_size_mb = sum(r.size_mb for r in rows if not r.is_installed)
    last_checked = rows[0].last_checked.isoformat() if rows else None
    return {
        "kind": kind,
        "pending": pending,
        "installed_recent": installed[:10],
        "total_pending": len(pending),
        "total_size_mb": round(total_size_mb, 2),
        "last_checked": last_checked,
    }


# ===================================================================
# GET /windows/status -> live progress
# ===================================================================
@router.get("/windows/status")
async def update_status() -> dict:
    """Live progress of a check or install operation."""
    return update_progress.to_dict()


# ===================================================================
# POST /windows/check  -> re-search and cache results
# ===================================================================
@router.post("/windows/check")
async def trigger_windows_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Search Windows Update for pending Software updates."""
    return await _check_wua(db, kind="windows", wua_type="Software")


@router.post("/drivers/check")
async def trigger_drivers_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Search Windows Update for pending Driver updates."""
    return await _check_wua(db, kind="driver", wua_type="Driver")


@_claims_update_slot("check")
async def _check_wua(db: AsyncSession, *, kind: str, wua_type: str) -> dict:
    """Shared check helper for either Software or Driver updates."""
    logger.info(f"POST /api/updates/{kind}/check")
    try:
        found = await check_for_updates(wua_type)
    except WindowsUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    now = datetime.now(UTC)

    # Upsert by update_id, scoped to this kind
    existing_q = await db.execute(select(WindowsUpdateORM).where(WindowsUpdateORM.kind == kind))
    existing = {r.update_id: r for r in existing_q.scalars().all()}

    found_ids: set[str] = set()
    new_count = 0
    for u in found:
        found_ids.add(u.update_id)
        row = existing.get(u.update_id)
        if row is None:
            row = WindowsUpdateORM(update_id=u.update_id, kind=kind)
            db.add(row)
            new_count += 1
        row.kind = kind
        row.title = u.title
        row.description = u.description
        row.kb_articles = ",".join(u.kb_articles)
        row.categories = ",".join(u.categories)
        row.severity = u.severity
        row.size_mb = u.size_mb
        row.is_downloaded = u.is_downloaded
        row.requires_reboot = u.requires_reboot
        row.release_date = u.release_date or ""
        row.is_installed = False
        row.last_checked = now

    # Mark previously-pending of this kind that are no longer pending as installed
    for uid, row in existing.items():
        if uid not in found_ids and not row.is_installed:
            row.is_installed = True
            row.install_result = 2

    await db.commit()
    if found:
        label = "تحديثات Windows" if kind == "windows" else "تحديثات تعريفات"
        notifications.notify("HomeUpdater — محدِّث المنزل", f"توفّرت {len(found)} {label}")
    return {
        "kind": kind,
        "total_pending": len(found),
        "new": new_count,
        "checked_at": now.isoformat(),
        "updates": [u.to_dict() for u in found],
    }


# ===================================================================
# POST /windows/install  -> install selected updates
# ===================================================================
@router.post("/windows/install")
async def trigger_windows_install(
    payload: InstallRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _install_wua(db, payload, kind="windows")


@router.post("/drivers/install")
async def trigger_drivers_install(
    payload: InstallRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _install_wua(db, payload, kind="driver")


@_claims_update_slot("install")
async def _install_wua(db: AsyncSession, payload: InstallRequest, *, kind: str) -> dict:
    update_ids = list(payload.update_ids)
    if not update_ids:
        q = await db.execute(
            select(WindowsUpdateORM).where(
                WindowsUpdateORM.is_installed.is_(False),
                WindowsUpdateORM.kind == kind,
            )
        )
        update_ids = [r.update_id for r in q.scalars().all()]
    if not update_ids:
        raise HTTPException(
            status_code=400,
            detail=f"No pending {kind} updates - run check first",
        )

    logger.info(f"POST /api/updates/{kind}/install ({len(update_ids)} updates)")
    try:
        result = await install_updates(update_ids)
    except WindowsUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    by_id: dict[str, dict] = {r["update_id"]: r for r in result["results"]}
    rows_q = await db.execute(
        select(WindowsUpdateORM).where(WindowsUpdateORM.update_id.in_(update_ids))
    )
    for row in rows_q.scalars().all():
        r = by_id.get(row.update_id)
        if r:
            row.install_result = r["result_code"]
            row.is_installed = bool(r["succeeded"])
    await db.commit()
    return result


# ===================================================================
# Software (winget) endpoints — Phase 1.5
# ===================================================================
@router.get("/software")
async def list_software(db: AsyncSession = Depends(get_db)) -> dict:
    """Cached list of winget packages with available upgrades."""
    result = await db.execute(
        select(SoftwarePackageORM).order_by(SoftwarePackageORM.last_checked.desc())
    )
    rows = result.scalars().all()
    pending = [r.to_dict() for r in rows if not r.is_installed]
    last_checked = rows[0].last_checked.isoformat() if rows else None
    return {
        "pending": pending,
        "total_pending": len(pending),
        "last_checked": last_checked,
    }


@router.post("/software/check")
@_claims_update_slot("check")
async def trigger_software_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Run `winget upgrade` to find packages with new versions."""
    logger.info("POST /api/updates/software/check")
    try:
        found, degraded = await list_software_updates()
    except SoftwareUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    now = datetime.now(UTC)
    existing_q = await db.execute(select(SoftwarePackageORM))
    existing = {r.package_id: r for r in existing_q.scalars().all()}

    found_ids: set[str] = set()
    new_count = 0
    for pkg in found:
        found_ids.add(pkg.package_id)
        row = existing.get(pkg.package_id)
        if row is None:
            row = SoftwarePackageORM(package_id=pkg.package_id)
            db.add(row)
            new_count += 1
        row.name = pkg.name
        row.current_version = pkg.current_version
        row.available_version = pkg.available_version
        row.source = pkg.source
        row.size_mb = pkg.size_mb
        row.is_installed = False
        row.last_checked = now

    # Anything that no longer appears must have been upgraded externally — but
    # ONLY trust that on a clean winget run. A degraded/partial result would
    # otherwise mark still-pending packages as "installed" and hide real upgrades.
    if not degraded:
        for pkg_id, row in existing.items():
            if pkg_id not in found_ids and not row.is_installed:
                row.is_installed = True
                row.install_result = 0

    await db.commit()
    if found:
        notifications.notify("HomeUpdater — محدِّث المنزل", f"توفّرت {len(found)} تحديثات برامج")
    return {
        "total_pending": len(found),
        "new": new_count,
        "checked_at": now.isoformat(),
        "updates": [u.to_dict() for u in found],
    }


class SoftwareInstallRequest(BaseModel):
    """POST /software/install body."""

    package_ids: list[str] = Field(default_factory=list)


@router.post("/software/install")
@_claims_update_slot("install")
async def trigger_software_install(
    payload: SoftwareInstallRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run `winget upgrade <id>` for each chosen package."""
    package_ids = list(payload.package_ids)
    if not package_ids:
        q = await db.execute(
            select(SoftwarePackageORM).where(SoftwarePackageORM.is_installed.is_(False))
        )
        package_ids = [r.package_id for r in q.scalars().all()]
    if not package_ids:
        raise HTTPException(status_code=400, detail="No pending packages - run check first")

    logger.info(f"POST /api/updates/software/install ({len(package_ids)} packages)")
    try:
        result = await install_many(package_ids)
    except SoftwareUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    by_id: dict[str, dict] = {r["package_id"]: r for r in result["results"]}
    rows_q = await db.execute(
        select(SoftwarePackageORM).where(SoftwarePackageORM.package_id.in_(package_ids))
    )
    for row in rows_q.scalars().all():
        r = by_id.get(row.package_id)
        if r:
            row.install_result = r["exit_code"]
            row.is_installed = bool(r["succeeded"])
    await db.commit()
    return result
