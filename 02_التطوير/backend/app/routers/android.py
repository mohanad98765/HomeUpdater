"""
Android router - manage phones connected via ADB over TCP/IP.

Endpoints (mounted under /api/android):
  GET    /pair/candidates               -> phones the app already found, to pick from
  POST   /pair/auto                     -> pair with only a six-digit code (no mDNS)
  POST   /pair/qr                       -> start a QR pairing session
  GET    /pair/qr                       -> its status (polled while the dialog is open)
  GET    /pair/qr.svg                   -> the code itself, as an inline SVG
  POST   /pair/qr/choose                -> pick a phone when several arrive at once
  DELETE /pair/qr                       -> end the session and forget the password
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

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import AndroidDeviceORM
from ..services import android_autopair, android_qr
from ..services.android import (
    AndroidError,
    discover_connect_port,
    list_apps,
    open_play_store,
    pair,
    probe,
)

router = APIRouter()


# ==================================================================
# Request schemas
# ==================================================================
class AddDeviceRequest(BaseModel):
    host: str = Field(..., description="Phone IP address")
    port: int = Field(default=5555, ge=1, le=65535)


class PairRequest(BaseModel):
    host: str = Field(..., description="Phone IP address (from the pairing dialog)")
    port: int = Field(..., ge=1, le=65535, description="Pairing port (changes each time)")
    code: str = Field(..., description="Six-digit pairing code shown on the phone")


class DiscoverRequest(BaseModel):
    host: str = Field(..., description="Phone IP address")


class UpdateDeviceRequest(BaseModel):
    custom_name: str | None = Field(default=None, max_length=255)


# ==================================================================
# Pairing with nothing but a six-digit code
#
# The QR and manual flows both need the hub to learn a random port the phone chose.
# Android publishes it over mDNS, and on a network that does not carry multicast
# between Wi-Fi and Ethernet — measured on the target network: zero mDNS packets from
# the phone in 60s while ping answers in 40ms — the hub never hears it.
#
# Asking the operator to read the port off the phone, or to enable multicast forwarding
# on their router, is asking a shop owner to become a network engineer in order to add a
# phone. So the hub finds the port by looking instead of listening. See
# services/android_autopair.py.
# ==================================================================
class AutoPairRequest(BaseModel):
    host: str = Field(min_length=7, max_length=45)
    code: str = Field(pattern=r"^\d{6}$")


@router.get("/pair/candidates")
async def pair_candidates(db: AsyncSession = Depends(get_db)) -> dict:
    """Phones already seen by the network scan, so the operator picks one instead of
    typing an address. Ordered by how likely each is to be the phone in their hand."""
    from ..models.orm import DeviceORM

    rows = (await db.execute(select(DeviceORM).where(DeviceORM.ip != ""))).scalars().all()
    known = {d.host for d in (await db.execute(select(AndroidDeviceORM))).scalars().all()}

    def rank(d) -> tuple:
        # A device the scan already called a phone first, then anything else; already
        # registered phones last, since they do not need pairing again.
        return (d.ip in known, d.device_type != "phone", d.ip)

    candidates = [
        {
            "ip": d.ip,
            "name": d.custom_name or d.hostname or d.vendor or d.ip,
            "vendor": d.vendor,
            "device_type": d.device_type,
            "already_added": d.ip in known,
        }
        for d in sorted(rows, key=rank)
    ]
    return {"candidates": candidates, "total": len(candidates)}


@router.post("/pair/auto")
async def auto_pair(payload: AutoPairRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Pair, connect, probe and register — the operator supplied only a code.

    Slow by nature (a port scan plus a pairing handshake), so the client is expected to
    wait rather than poll: there is nothing useful to report in between beyond "still
    looking", and a half-finished pairing is not a state worth exposing.
    """
    try:
        paired = await android_autopair.pair_with_code(payload.host, payload.code)
        connect_port = await android_autopair.find_connect_port(
            payload.host, exclude=paired["pairing_port"]
        )
        if connect_port is None:
            raise AndroidError(
                "تمّ الإقران لكن تعذّر إيجاد منفذ الاتّصال. أبقِ «تصحيح الأخطاء "
                "اللاسلكي» مفعّلًا وأعد المحاولة."
            )
        info = await probe(payload.host, connect_port)
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AndroidDeviceORM).where(
                AndroidDeviceORM.host == payload.host,
                AndroidDeviceORM.port == connect_port,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AndroidDeviceORM(host=payload.host, port=connect_port, first_seen=now)
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
    logger.info(f"auto-paired and registered {payload.host}:{connect_port}")
    return {"device": row.to_dict(), "pairing_port": paired["pairing_port"]}


# ==================================================================
# QR pairing (Android 11+)
#
# The hub shows a code, the phone scans it, and the phone starts advertising a pairing
# service. Nothing here asks a person to read a port off a screen. See
# services/android_qr.py for what about this flow is verified and what is not.
# ==================================================================
class ChooseRequest(BaseModel):
    instance: str = Field(min_length=1, max_length=128)


class StartQrRequest(BaseModel):
    # The phone the operator picked. Optional, but with it the flow needs nothing from
    # the network beyond what a ping already proves: after the scan the phone opens a
    # pairing port, the password is the one in our own code, and sweeping that single
    # host finds the port. Without it the session can only listen for an mDNS
    # announcement, which many networks do not carry.
    host: str = Field(default="", max_length=45)


@router.post("/pair/qr")
async def start_qr_pairing(payload: StartQrRequest | None = None) -> dict:
    """Mint a pairing password and start watching for the phone that scanned it."""
    try:
        session = await android_qr.start(target_host=(payload.host if payload else ""))
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.public()


@router.get("/pair/qr")
async def qr_pairing_status() -> dict:
    """Polled while the dialog is open. Returns ``{"status": "none"}`` once the session
    is gone, so a stale page cannot keep reporting a pairing that no longer exists."""
    session = android_qr.current()
    if session is None:
        return {"status": "none"}
    return session.public()


@router.get("/pair/qr.svg")
async def qr_pairing_image() -> Response:
    """The code, rendered where the password was generated.

    ``no-store``: this image *is* the credential, and a cached copy in a WebView2 disk
    cache would outlive the two-minute session it belongs to.
    """
    session = android_qr.current()
    if session is None or not session.payload:
        raise HTTPException(status_code=404, detail="no_active_session")
    svg = android_qr.render_qr_svg(session.payload)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@router.post("/pair/qr/choose")
async def choose_qr_phone(payload: ChooseRequest) -> dict:
    """Two phones arrived at once. Pairing with a coin flip would hand the password to
    the wrong one, so the operator says which."""
    try:
        session = await android_qr.choose(payload.instance)
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.public()


@router.delete("/pair/qr")
async def cancel_qr_pairing() -> dict:
    """End the session. A pairing code left live is a code someone else can use."""
    await android_qr.cancel()
    return {"cancelled": True}


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
# POST /pair  -> pair with Wireless debugging (Android 11+)
# ==================================================================
@router.post("/pair")
async def pair_device(payload: PairRequest) -> dict:
    """Pair with a phone's Wireless debugging using the six-digit code.

    One-time per phone. Afterwards, add it with its *connect* IP:port.
    """
    logger.info(f"POST /api/android/pair - {payload.host}:{payload.port}")
    try:
        await pair(payload.host, payload.port, payload.code)
    except AndroidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Best-effort: auto-discover the (different, random) connect port so the UI
    # can fill it in — pairing succeeding must not depend on this.
    connect_port = await discover_connect_port(payload.host)
    return {"paired": True, "host": payload.host, "connect_port": connect_port}


# ==================================================================
# POST /discover  -> find the current Wireless-debugging connect port
# ==================================================================
@router.post("/discover")
async def discover(payload: DiscoverRequest) -> dict:
    """Auto-detect a phone's connect port via adb mDNS (it changes each time)."""
    port = await discover_connect_port(payload.host)
    if port is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "لم يُعثر على منفذ الاتصال — تأكّد أن «التصحيح اللاسلكي» "
                "مُفعّل والجوّال على نفس الشبكة."
            ),
        )
    return {"host": payload.host, "connect_port": port}


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
