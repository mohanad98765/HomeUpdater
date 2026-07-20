"""
Devices router (Phase 1.3 - SQLite-backed).

Endpoints:
  GET    /api/devices                -> list known devices (sorted by IP)
  GET    /api/devices/info           -> network info snapshot
  GET    /api/devices/stats          -> counts (total / online / by_type)
  GET    /api/devices/scan/status    -> live scan progress
  POST   /api/devices/scan           -> trigger ARP/ICMP scan
  GET    /api/devices/{id}           -> single device details
  PATCH  /api/devices/{id}           -> update custom_name / notes

Mounted in main.py with prefix /api/devices.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..models.orm import DeviceORM
from ..services import adaptive_persistence
from ..services.discovery import DiscoveryError, scan_network
from ..services.network_utils import (
    get_local_subnet,
    get_network_info,
    is_valid_cidr,
    list_local_interfaces,
)
from ..services.progress import scan_progress

router = APIRouter()


# ===================================================================
# Schemas (request bodies)
# ===================================================================
class ScanRequest(BaseModel):
    """Optional override for POST /scan."""

    subnet: str | None = Field(
        default=None,
        description="CIDR like '192.168.1.0/24'. Omit for auto-detection.",
    )


class DeviceUpdate(BaseModel):
    """PATCH body for device fields the user can edit."""

    custom_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)


# ===================================================================
# GET /api/devices  -> list
# ===================================================================
@router.get("")
async def list_devices(db: AsyncSession = Depends(get_db)) -> dict:
    """All known devices, sorted by IP."""
    result = await db.execute(select(DeviceORM))
    devices = sorted(result.scalars().all(), key=lambda d: _ip_sort_key(d.ip))
    return {
        "devices": [d.to_dict() for d in devices],
        "total": len(devices),
        "subnet": get_local_subnet(),
    }


# ===================================================================
# GET /api/devices/stats  -> counts
# ===================================================================
@router.get("/stats")
async def device_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Counts by status and type — drives the dashboard cards."""
    total_q = await db.execute(select(func.count()).select_from(DeviceORM))
    total = total_q.scalar_one()

    online_q = await db.execute(
        select(func.count()).select_from(DeviceORM).where(DeviceORM.is_online.is_(True))
    )
    online = online_q.scalar_one()

    by_type_q = await db.execute(
        select(DeviceORM.device_type, func.count()).group_by(DeviceORM.device_type)
    )
    by_type = {row[0]: row[1] for row in by_type_q.all()}

    return {
        "total": total,
        "online": online,
        "offline": total - online,
        "by_type": by_type,
    }


# ===================================================================
# GET /api/devices/info  -> network snapshot
# ===================================================================
@router.get("/info")
async def network_info(db: AsyncSession = Depends(get_db)) -> dict:
    """Full network snapshot for the UI."""
    info = get_network_info()
    stored = await db.execute(select(func.count()).select_from(DeviceORM))
    return {
        "local_ip": info.local_ip if info else None,
        "netmask": info.netmask if info else None,
        "raw_subnet": info.raw_subnet if info else None,
        "suggested_subnet": info.suggested_subnet if info else "192.168.1.0/24",
        "gateway_ip": info.gateway_ip if info else None,
        "interface_name": info.interface_name if info else None,
        "interfaces": list_local_interfaces(),
        "stored_devices": stored.scalar_one(),
    }


# ===================================================================
# GET /api/devices/scan/status  -> live progress
# ===================================================================
@router.get("/scan/status")
async def scan_status() -> dict:
    """Live progress polled by the UI while a scan is in-flight."""
    return scan_progress.to_dict()


# ===================================================================
# POST /api/devices/scan  -> trigger scan, persist results
# ===================================================================
async def _persist_scan(db: AsyncSession, result: dict, now: datetime) -> int:
    """Upsert scan results; mark missing devices offline. Returns NEW-row count.

    Handles the two ARP quirks: MAC-less hosts (mac=None so several coexist) and
    two IPs sharing one MAC (collapsed to one row via the ``existing`` map)."""
    existing_q = await db.execute(select(DeviceORM))
    existing = {(d.mac or d.ip): d for d in existing_q.scalars().all()}

    found_keys: set[str] = set()
    new_count = 0

    for raw in result["devices"]:
        key = raw["mac"] or raw["ip"]
        found_keys.add(key)

        if key in existing:
            d = existing[key]
            d.last_seen = now
            d.is_online = True
            d.ip = raw["ip"]
            if raw["hostname"]:
                d.hostname = raw["hostname"]
            if raw["vendor"]:
                d.vendor = raw["vendor"]
            d.device_type = raw["device_type"]
        else:
            d = DeviceORM(
                ip=raw["ip"],
                mac=raw["mac"] or None,  # None (not "") so multiple MAC-less hosts coexist
                hostname=raw["hostname"] or "",
                vendor=raw["vendor"] or "",
                device_type=raw["device_type"],
                is_online=True,
                first_seen=now,
                last_seen=now,
            )
            db.add(d)
            existing[key] = d
            new_count += 1

    for key, d in existing.items():
        if key not in found_keys:
            d.is_online = False

    await db.commit()
    return new_count


async def _run_scan_bg(target: str) -> None:
    """Run the (possibly slow) scan + persist in the background so the POST
    returns immediately. Progress/completion are exposed via /scan/status."""
    started_at = time.time()
    now = datetime.now(UTC)
    try:
        result = await scan_network(target)
    except DiscoveryError as exc:
        logger.error(f"Discovery failed: {exc}")
        return  # scan_network already marked scan_progress.fail()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan crashed")
        scan_progress.fail(str(exc))
        return

    try:
        async with SessionLocal() as db:
            new_count = await _persist_scan(db, result, now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Persisting scan results failed")
        scan_progress.fail(f"تعذّر حفظ نتائج المسح: {exc}")
        return

    count = len(result["devices"])
    scan_progress.finish(count)  # mark done only AFTER results are saved
    logger.info(
        f"Scan finished in {round(time.time() - started_at, 2)}s - "
        f"subnet={result['subnet']} total={count} new={new_count}"
    )
    if settings.adaptive_timeout_persistence:
        adaptive_persistence.save_to_disk()  # best-effort: warm-start the next scan


@router.post("/scan")
async def trigger_scan(req: ScanRequest = ScanRequest()) -> dict:
    """Start a network scan in the BACKGROUND and return immediately.

    A scan can take a while (a busy /24, or nmap on the user's machine), so
    blocking the HTTP request would time out on the client — the exact symptom
    where the scan "fails" even though devices were found. Instead we kick it off
    and the UI polls GET /api/devices/scan/status for live progress + completion,
    then refetches the device list."""
    if scan_progress.is_running:
        raise HTTPException(
            status_code=409,
            detail="مسح آخر قيد التنفيذ بالفعل / A scan is already running",
        )

    target_subnet = req.subnet
    if target_subnet and not is_valid_cidr(target_subnet):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid CIDR: '{target_subnet}'. Example: 192.168.1.0/24",
        )

    target = target_subnet or get_local_subnet()
    logger.info(f"POST /api/devices/scan -> background scan on {target}")
    # Mark in-progress synchronously: rejects a second POST (409) and makes the
    # UI's first /status poll already see the run.
    scan_progress.begin(target)
    asyncio.create_task(_run_scan_bg(target))
    return {"started": True, "subnet": target}


# ===================================================================
# DELETE /api/devices  -> clear the table
# ===================================================================
@router.delete("")
async def clear_devices(db: AsyncSession = Depends(get_db)) -> dict:
    """Remove every stored device. Useful before a fresh re-scan."""
    count_q = await db.execute(select(func.count()).select_from(DeviceORM))
    before = count_q.scalar_one()
    await db.execute(delete(DeviceORM))
    await db.commit()
    logger.info(f"DELETE /api/devices - removed {before} device(s)")
    return {"deleted": int(before)}


# ===================================================================
# GET /api/devices/{id}  -> single device
# ===================================================================
@router.get("/{device_id}")
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    device = await db.get(DeviceORM, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device.to_dict()


# ===================================================================
# PATCH /api/devices/{id}  -> update editable fields
# ===================================================================
@router.patch("/{device_id}")
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = await db.get(DeviceORM, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if payload.custom_name is not None:
        device.custom_name = payload.custom_name.strip()
    if payload.notes is not None:
        device.notes = payload.notes.strip()

    await db.commit()
    await db.refresh(device)
    logger.info(f"Updated device #{device_id}: name='{device.custom_name}'")
    return device.to_dict()


# ===================================================================
# Helpers
# ===================================================================
def _ip_sort_key(ip: str) -> tuple:
    try:
        return tuple(int(p) for p in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)
