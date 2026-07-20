"""SSH / Linux host update-management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import SSHHostORM
from ..services import ssh

router = APIRouter()


class AddHost(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(..., min_length=1)
    password: str = Field(default="")
    custom_name: str = Field(default="")


async def _get_host(host_id: int, db: AsyncSession) -> SSHHostORM:
    row = await db.get(SSHHostORM, host_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Host not found")
    return row


@router.get("/hosts")
async def list_hosts(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        (await db.execute(select(SSHHostORM).order_by(SSHHostORM.last_seen.desc()))).scalars().all()
    )
    return {"hosts": [r.to_dict() for r in rows], "total": len(rows)}


@router.post("/hosts")
async def add_host(payload: AddHost, db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(SSHHostORM).where(
                SSHHostORM.host == payload.host,
                SSHHostORM.port == payload.port,
                SSHHostORM.username == payload.username,
            )
        )
    ).scalar_one_or_none()

    # Verify the connection (and detect the OS) before saving. If we already trust
    # a host key for this host, verify it (TOFU); otherwise capture it.
    try:
        info = await ssh.probe(
            payload.host,
            payload.port,
            payload.username,
            payload.password,
            (row.host_key or None) if row else None,
        )
    except ssh.SSHError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if row is None:
        row = SSHHostORM(
            host=payload.host, port=payload.port, username=payload.username, first_seen=now
        )
        db.add(row)
    if payload.password:
        row.password = payload.password
    if payload.custom_name:
        row.custom_name = payload.custom_name
    if info.get("host_key"):
        row.host_key = info["host_key"]  # trust-on-first-use / re-confirm
    row.os_name = info["os_name"]
    row.os_id = info["os_id"]
    row.pkg_manager = info["pkg_manager"]
    row.is_online = True
    row.last_seen = now
    await db.commit()
    await db.refresh(row)
    return row.to_dict()


@router.delete("/hosts/{host_id}")
async def remove_host(host_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    await _get_host(host_id, db)
    await db.execute(delete(SSHHostORM).where(SSHHostORM.id == host_id))
    await db.commit()
    return {"deleted": host_id}


@router.post("/hosts/{host_id}/check")
async def check(host_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _get_host(host_id, db)
    try:
        result = await ssh.check_updates(
            row.host, row.port, row.username, row.password, row.pkg_manager, row.host_key or None
        )
    except ssh.SSHError as exc:
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
        return await ssh.apply_updates(
            row.host, row.port, row.username, row.password, row.pkg_manager, row.host_key or None
        )
    except ssh.SSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
