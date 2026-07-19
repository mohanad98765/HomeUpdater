"""
Android router - manage phones connected via ADB over TCP/IP.

Endpoints (mounted under /api/android):
  GET    /devices                       -> list registered phones
  POST   /devices                       -> add + probe a phone by IP:port
  DELETE /devices/{id}                  -> remove a phone
  POST   /devices/{id}/refresh          -> re-probe a phone to update info
  PATCH  /devices/{id}                  -> update custom_name
  GET    /devices/{id}/apps             -> list installed 3rd-party apps
  POST   /devices/{id}/apps/{pkg}/open  -> open Play Store page on the phone
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import AndroidDeviceORM
from ..services.android import (
    AndroidError,
    list_apps,
    open_play_store,
    probe,
)

router = APIRouter()


# ==================================================================
# Request schemas
# ==================================================================
class AddDeviceRequest(BaseModel):
    host: str = Field(..., description="Phone IP address")
    port: int = Field(default=5555, ge=1, le=65535)


class UpdateDeviceRequest(BaseModel):
    custom_name: str | None = Field(default=None, max_length=255)


# ==================================================================
# GET /devices  -> list
# ==================================================================
@router.get("/devices")
async def list_devices(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(AndroidDeviceORM).order_by(AndroidDeviceORM.last_seen.desc()))
    rows = result.scalars().all()
    return {
        "devices": [r.to_dict() for r in rows],
        "total": len(rows),
    }


# ==================================================================
# POST /devices  -> add + probe
# ==================================================================
@router.post("/devices")
async def add_device(
    payload: AddDeviceRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info(f"POST /api/android/devices - {payload.host}:{payload.port}")

    # Probe the phone first — fail fast if unreachable / auth denied
    try:
        info = await probe(payload.host, payload.port)
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)

    # Upsert by (host, port)
    existing_q = await db.execute(
        select(AndroidDeviceORM).where(
            AndroidDeviceORM.host == payload.host,
            AndroidDeviceORM.port == payload.port,
        )
    )
    row = existing_q.scalar_one_or_none()
    if row is None:
        row = AndroidDeviceORM(
            host=payload.host,
            port=payload.port,
            first_seen=now,
        )
        db.add(row)

    row.serial = info.serial
    row.manufacturer = info.manufacturer
    row.model = info.model
    row.brand = info.brand
    row.android_version = info.android_version
    row.sdk_version = info.sdk_version
    row.security_patch = info.security_patch
    row.is_online = True
    row.last_seen = now

    await db.commit()
    await db.refresh(row)
    return row.to_dict()


# ==================================================================
# DELETE /devices/{id}
# ==================================================================
@router.delete("/devices/{device_id}")
async def remove_device(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(AndroidDeviceORM, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.execute(delete(AndroidDeviceORM).where(AndroidDeviceORM.id == device_id))
    await db.commit()
    return {"deleted": device_id}


# ==================================================================
# PATCH /devices/{id}  -> custom name
# ==================================================================
@router.patch("/devices/{device_id}")
async def update_device(
    device_id: int,
    payload: UpdateDeviceRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(AndroidDeviceORM, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if payload.custom_name is not None:
        row.custom_name = payload.custom_name.strip()
    await db.commit()
    await db.refresh(row)
    return row.to_dict()


# ==================================================================
# POST /devices/{id}/refresh  -> re-probe
# ==================================================================
@router.post("/devices/{device_id}/refresh")
async def refresh_device(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(AndroidDeviceORM, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        info = await probe(row.host, row.port)
        row.serial = info.serial
        row.manufacturer = info.manufacturer
        row.model = info.model
        row.brand = info.brand
        row.android_version = info.android_version
        row.sdk_version = info.sdk_version
        row.security_patch = info.security_patch
        row.is_online = True
        row.last_seen = datetime.now(UTC)
    except AndroidError as exc:
        row.is_online = False
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(row)
    return row.to_dict()


# ==================================================================
# GET /devices/{id}/apps  -> installed apps
# ==================================================================
@router.get("/devices/{device_id}/apps")
async def get_apps(
    device_id: int,
    include_system: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(AndroidDeviceORM, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        apps = await list_apps(row.host, row.port, include_system=include_system)
    except AndroidError as exc:
        row.is_online = False
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row.is_online = True
    row.last_seen = datetime.now(UTC)
    await db.commit()

    return {
        "device": row.to_dict(),
        "apps": [a.to_dict() for a in apps],
        "total": len(apps),
    }


# ==================================================================
# POST /devices/{id}/apps/{pkg}/open  -> open Play Store
# ==================================================================
@router.post("/devices/{device_id}/apps/{package_name}/open")
async def open_app_in_store(
    device_id: int,
    package_name: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(AndroidDeviceORM, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        await open_play_store(row.host, row.port, package_name)
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "opened", "package_name": package_name}
