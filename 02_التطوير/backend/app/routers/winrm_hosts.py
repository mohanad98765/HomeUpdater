"""Remote Windows host update-management endpoints (WinRM / winget)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import WinRMHostORM
from ..services import winrm_hosts as winrm

router = APIRouter()


class AddHost(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(default=winrm.DEFAULT_PORT, ge=1, le=65535)
    username: str = Field(..., min_length=1)
    password: str = Field(default="")
    use_https: bool = Field(default=False)
    # Whitelisted at the API boundary so a caller can't pick an unsafe transport.
    transport: Literal["ntlm", "kerberos", "basic"] = Field(default="ntlm")
    verify_tls: bool = Field(default=False)
    custom_name: str = Field(default="")


async def _get_host(host_id: int, db: AsyncSession) -> WinRMHostORM:
    row = await db.get(WinRMHostORM, host_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Host not found")
    return row


@router.get("/hosts")
async def list_hosts(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        (await db.execute(select(WinRMHostORM).order_by(WinRMHostORM.last_seen.desc())))
        .scalars()
        .all()
    )
    return {"hosts": [r.to_dict() for r in rows], "total": len(rows)}


@router.post("/hosts")
async def add_host(payload: AddHost, db: AsyncSession = Depends(get_db)) -> dict:
    # basic auth only base64-encodes the password: refuse it over plain HTTP so
    # admin credentials are never sent in the clear on the LAN.
    if payload.transport == "basic" and not payload.use_https:
        raise HTTPException(
            status_code=400,
            detail="مصادقة basic فوق HTTP تُرسل كلمة المرور بلا تشفير — استخدم HTTPS أو ntlm.",
        )
    # Verify the connection (and detect the OS) before saving.
    try:
        info = await winrm.probe(
            payload.host,
            payload.port,
            payload.username,
            payload.password,
            payload.use_https,
            payload.transport,
            payload.verify_tls,
        )
    except winrm.WinRMHostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(WinRMHostORM).where(
                WinRMHostORM.host == payload.host,
                WinRMHostORM.port == payload.port,
                WinRMHostORM.username == payload.username,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = WinRMHostORM(
            host=payload.host, port=payload.port, username=payload.username, first_seen=now
        )
        db.add(row)
    if payload.password:
        row.password = payload.password
    if payload.custom_name:
        row.custom_name = payload.custom_name
    row.use_https = payload.use_https
    row.transport = payload.transport
    row.verify_tls = payload.verify_tls
    row.os_name = info["os_name"]
    row.os_version = info["os_version"]
    row.hostname = info["hostname"]
    row.has_winget = info["has_winget"]
    row.is_online = True
    row.last_seen = now
    await db.commit()
    await db.refresh(row)
    return row.to_dict()


@router.delete("/hosts/{host_id}")
async def remove_host(host_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    await _get_host(host_id, db)
    await db.execute(delete(WinRMHostORM).where(WinRMHostORM.id == host_id))
    await db.commit()
    return {"deleted": host_id}


@router.post("/hosts/{host_id}/check")
async def check(host_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_host(host_id, db)
    try:
        result = await winrm.check_updates(
            row.host,
            row.port,
            row.username,
            row.password,
            row.use_https,
            row.transport,
            row.verify_tls,
        )
    except winrm.WinRMHostError as exc:
        row.is_online = False
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    row.is_online = True
    row.last_seen = datetime.now(UTC)
    await db.commit()
    return result


@router.post("/hosts/{host_id}/upgrade")
async def upgrade(host_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_host(host_id, db)
    try:
        return await winrm.apply_updates(
            row.host,
            row.port,
            row.username,
            row.password,
            row.use_https,
            row.transport,
            row.verify_tls,
        )
    except winrm.WinRMHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
