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
from ..models.orm import (
    HUB_DEVICE_ID,
    InstalledSoftwareORM,
    SoftwarePackageORM,
    UpdateCheckORM,
    WindowsUpdateORM,
)
from ..services import audit, notifications
from ..services.software_updates import (
    SoftwareUpdateError,
    install_many,
    list_installed_software,
    list_software_updates,
)
from ..services.update_progress import update_progress
from ..services.windows_updates import (
    WindowsUpdateError,
    check_for_updates,
    install_updates,
)

router = APIRouter()

# Not a WUA result code: WUA uses 0..5, so a negative value cannot collide with one. It
# means "Windows stopped offering this", which is a fact we know, unlike "it was
# installed", which we were inferring.
NO_LONGER_OFFERED = -1


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
        # These endpoints are about THIS PC; fleet rows carry a real device_id.
        .where(WindowsUpdateORM.device_id == HUB_DEVICE_ID, WindowsUpdateORM.kind == kind).order_by(
            WindowsUpdateORM.last_checked.desc()
        )
    )
    rows = result.scalars().all()
    pending = [r.to_dict() for r in rows if not r.is_installed]
    installed = [r.to_dict() for r in rows if r.is_installed]
    total_size_mb = sum(r.size_mb for r in rows if not r.is_installed)
    # "Last checked" is a fact about the CHECK, not about the newest row. Reading it off
    # the rows meant a check that found nothing left no trace: the user pressed the
    # button, the app found his machine already up to date, and the screen went on
    # insisting he had never checked — on a tab with no rows, forever.
    check = await _last_check(db, kind)
    return {
        "kind": kind,
        "pending": pending,
        "installed_recent": installed[:10],
        "total_pending": len(pending),
        "total_size_mb": round(total_size_mb, 2),
        "last_checked": check.checked_at.isoformat() if check else None,
        # None = never checked. 0 = checked, and there was genuinely nothing.
        "last_check_found": check.found if check else None,
    }


async def _last_check(db: AsyncSession, kind: str) -> UpdateCheckORM | None:
    row = await db.execute(
        select(UpdateCheckORM).where(
            UpdateCheckORM.device_id == HUB_DEVICE_ID, UpdateCheckORM.kind == kind
        )
    )
    return row.scalar_one_or_none()


async def _record_check(db: AsyncSession, kind: str, found: int, now: datetime) -> None:
    """Stamp that a check RAN. Called on every completed check, including empty ones —
    that is the whole point."""
    row = await _last_check(db, kind)
    if row is None:
        row = UpdateCheckORM(device_id=HUB_DEVICE_ID, kind=kind)
        db.add(row)
    row.checked_at = now
    row.found = found


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
    existing_q = await db.execute(
        select(WindowsUpdateORM).where(
            WindowsUpdateORM.device_id == HUB_DEVICE_ID, WindowsUpdateORM.kind == kind
        )
    )
    existing = {r.update_id: r for r in existing_q.scalars().all()}

    found_ids: set[str] = set()
    new_count = 0
    for u in found:
        found_ids.add(u.update_id)
        row = existing.get(u.update_id)
        if row is None:
            row = WindowsUpdateORM(device_id=HUB_DEVICE_ID, update_id=u.update_id, kind=kind)
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

    # An update that stopped being offered is no longer PENDING — but "not offered" is
    # not "installed". Windows also withdraws an update when it is superseded, expired,
    # declined or hidden, and Defender definitions are superseded several times a day.
    # Recording result code 2 ("Succeeded") here is what put updates nobody installed
    # into a hash-stamped report under "Applied updates"; ``applied_by_us`` stays False
    # so the pack can tell the two apart.
    for uid, row in existing.items():
        if uid not in found_ids and not row.is_installed:
            row.is_installed = True
            row.install_result = NO_LONGER_OFFERED

    await _record_check(db, kind, len(found), now)
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
                WindowsUpdateORM.device_id == HUB_DEVICE_ID,
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
        select(WindowsUpdateORM).where(
            WindowsUpdateORM.device_id == HUB_DEVICE_ID,
            WindowsUpdateORM.update_id.in_(update_ids),
        )
    )
    for row in rows_q.scalars().all():
        r = by_id.get(row.update_id)
        if r:
            row.install_result = r["result_code"]
            row.is_installed = bool(r["succeeded"])
            # The only place this is ever set. Everything the pack claims as applied
            # comes from here, where an install genuinely ran and reported success.
            row.applied_by_us = row.applied_by_us or bool(r["succeeded"])
    await db.commit()
    # الحدث الأهمّ في حزمة الدليل: أيّ تحديث ثُبِّت ومتى ونتيجته — هذا ما يُطالَب
    # بإثباته أمام المُراجِع، فيُسجَّل نجاحًا كان أو فشلًا.
    installed = int(result.get("installed", 0) or 0)
    total = int(result.get("total", len(update_ids)) or 0)
    await audit.record_safe(
        db,
        "update_install",
        target="this-pc",
        outcome="ok" if installed == total else "failed",
        detail={
            "kind": kind,
            "requested": total,
            "installed": installed,
            "reboot_required": bool(result.get("reboot_required", False)),
            "update_ids": update_ids[:50],
        },
    )
    return result


# ===================================================================
# Installed-software inventory — what IS on the machine, not what's outdated
# ===================================================================
@router.get("/inventory")
async def list_inventory(db: AsyncSession = Depends(get_db)) -> dict:
    """The stored inventory for THIS PC (product + version + source)."""
    rows = (
        (
            await db.execute(
                select(InstalledSoftwareORM)
                .where(InstalledSoftwareORM.device_id == HUB_DEVICE_ID)
                .order_by(InstalledSoftwareORM.name)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [r.to_dict() for r in rows],
        "total": len(rows),
        "last_seen": max((r.last_seen for r in rows), default=None).isoformat() if rows else None,
    }


@router.post("/inventory/refresh")
@_claims_update_slot("inventory")
async def refresh_inventory(db: AsyncSession = Depends(get_db)) -> dict:
    """Re-read ``winget list`` and upsert the inventory for THIS PC."""
    logger.info("POST /api/updates/inventory/refresh")
    try:
        items, degraded = await list_installed_software()
    except SoftwareUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    now = datetime.now(UTC)
    existing = {
        r.product_id: r
        for r in (
            (
                await db.execute(
                    select(InstalledSoftwareORM).where(
                        InstalledSoftwareORM.device_id == HUB_DEVICE_ID
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    new_count = 0
    for item in items:
        row = existing.get(item.product_id)
        if row is None:
            row = InstalledSoftwareORM(
                device_id=HUB_DEVICE_ID, product_id=item.product_id, first_seen=now
            )
            db.add(row)
            new_count += 1
        row.name = item.name
        row.version = item.version
        row.source = item.source
        if item.publisher:
            row.publisher = item.publisher  # keep an earlier value if winget has none
        row.last_seen = now

    # Prune products that are genuinely gone — but ONLY on a clean run. After a
    # degraded (non-zero) winget exit the output may be partial, and deleting
    # rows merely absent from it would erase real inventory.
    removed = 0
    if not degraded:
        seen = {i.product_id for i in items}
        for pid, row in existing.items():
            if pid not in seen:
                await db.delete(row)
                removed += 1

    await db.commit()
    # أثرٌ للتدقيق: ماذا جُرِد ومتى — أساس أي تقرير أصول لاحق.
    await audit.record_safe(
        db,
        "inventory",
        target="this-pc",
        outcome="degraded" if degraded else "ok",
        detail={"total": len(items), "new": new_count, "removed": removed},
    )
    return {
        "total": len(items),
        "new": new_count,
        "removed": removed,
        "degraded": degraded,
        "checked_at": now.isoformat(),
    }


# ===================================================================
# Software (winget) endpoints — Phase 1.5
# ===================================================================
@router.get("/software")
async def list_software(db: AsyncSession = Depends(get_db)) -> dict:
    """Cached list of winget packages with available upgrades."""
    result = await db.execute(
        select(SoftwarePackageORM)
        .where(SoftwarePackageORM.device_id == HUB_DEVICE_ID)
        .order_by(SoftwarePackageORM.last_checked.desc())
    )
    rows = result.scalars().all()
    pending = [r.to_dict() for r in rows if not r.is_installed]
    check = await _last_check(db, "software")  # the check, not the newest row — see above
    return {
        "pending": pending,
        "total_pending": len(pending),
        "last_checked": check.checked_at.isoformat() if check else None,
        "last_check_found": check.found if check else None,
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
    existing_q = await db.execute(
        select(SoftwarePackageORM).where(SoftwarePackageORM.device_id == HUB_DEVICE_ID)
    )
    existing = {r.package_id: r for r in existing_q.scalars().all()}

    found_ids: set[str] = set()
    new_count = 0
    for pkg in found:
        found_ids.add(pkg.package_id)
        row = existing.get(pkg.package_id)
        if row is None:
            row = SoftwarePackageORM(device_id=HUB_DEVICE_ID, package_id=pkg.package_id)
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

    await _record_check(db, "software", len(found), now)
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
            select(SoftwarePackageORM).where(
                SoftwarePackageORM.device_id == HUB_DEVICE_ID,
                SoftwarePackageORM.is_installed.is_(False),
            )
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
        select(SoftwarePackageORM).where(
            SoftwarePackageORM.device_id == HUB_DEVICE_ID,
            SoftwarePackageORM.package_id.in_(package_ids),
        )
    )
    for row in rows_q.scalars().all():
        r = by_id.get(row.package_id)
        if r:
            row.install_result = r["exit_code"]
            row.is_installed = bool(r["succeeded"])
    await db.commit()
    return result
