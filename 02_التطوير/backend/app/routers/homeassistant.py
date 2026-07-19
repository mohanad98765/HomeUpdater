"""Home Assistant integration endpoints (config + updates)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import HAConfigORM
from ..services import homeassistant as ha

router = APIRouter()


async def _get_config(db: AsyncSession) -> HAConfigORM | None:
    return (await db.execute(select(HAConfigORM).where(HAConfigORM.id == 1))).scalar_one_or_none()


class HAConfigIn(BaseModel):
    base_url: str = Field(default="")
    token: str = Field(default="")  # blank = keep the existing token
    enabled: bool = False


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_config(db)
    if row is None:
        return {
            "configured": False,
            "enabled": False,
            "connected": False,
            "base_url": "",
            "has_token": False,
        }
    out = {**row.to_dict(), "configured": bool(row.base_url and row.token), "connected": False}
    if row.enabled and row.base_url and row.token:
        try:
            info = await ha.check(row.base_url, row.token)
            out.update(
                {
                    "connected": True,
                    "version": info["version"],
                    "location_name": info["location_name"],
                }
            )
        except ha.HAError as exc:
            out["error"] = str(exc)
    return out


@router.post("/config")
async def set_config(payload: HAConfigIn, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_config(db)
    token = payload.token.strip() or (row.token if row else "")
    # Verify the connection before saving when enabling.
    if payload.enabled and payload.base_url and token:
        try:
            await ha.check(payload.base_url, token)
        except ha.HAError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        row = HAConfigORM(id=1)
        db.add(row)
    row.base_url = payload.base_url.strip()
    row.token = token
    row.enabled = payload.enabled
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return await status(db)


@router.get("/updates")
async def updates(db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_config(db)
    if row is None or not (row.enabled and row.base_url and row.token):
        raise HTTPException(status_code=400, detail="Home Assistant not configured/enabled")
    try:
        return await ha.get_updates(row.base_url, row.token)
    except ha.HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class InstallIn(BaseModel):
    entity_id: str


@router.post("/updates/install")
async def install(payload: InstallIn, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_config(db)
    if row is None or not (row.base_url and row.token):
        raise HTTPException(status_code=400, detail="Home Assistant not configured")
    try:
        return await ha.install_update(row.base_url, row.token, payload.entity_id)
    except ha.HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
