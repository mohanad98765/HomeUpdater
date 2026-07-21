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

# Keep a strong reference to the background scan task: asyncio only holds a weak
# ref, so without this the task can be garbage-collected mid-run, leaving
# scan_progress.is_running=True forever (every later POST /scan -> 409).
_bg_tasks: set[asyncio.Task] = set()


def _reap_scan_task(task: asyncio.Task) -> None:
    _bg_tasks.discard(task)
    # If the task ended without completing the progress lifecycle (GC, cancel, or
    # a crash after begin() but before finish/fail), don't strand the 409 gate.
    if not scan_progress.is_running:
        return
    if task.cancelled():
        reason = "أُلغيت العملية"
    else:
        exc = task.exception()
        reason = str(exc) if exc else "انتهت دون إكمال"
    scan_progress.fail(f"توقّف المسح: {reason}")


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
def _same_identity(hostname_a: str, vendor_a: str, hostname_b: str, vendor_b: str) -> bool:
    """Whether two observations plausibly describe the SAME physical device —
    used before moving user edits (name/notes) between rows. Agree if hostnames
    match, or a hostname side is empty; else fall back to vendor; else (no signal)
    assume same rather than strand the user's rename."""
    ha, hb = (hostname_a or "").strip().lower(), (hostname_b or "").strip().lower()
    if ha and hb:
        return ha == hb
    va, vb = (vendor_a or "").strip().lower(), (vendor_b or "").strip().lower()
    if va and vb:
        return va == vb
    return True


def _apply_scan_fields(d: DeviceORM, raw: dict, now: datetime) -> None:
    d.last_seen = now
    d.is_online = True
    d.ip = raw["ip"]
    if raw["hostname"]:
        d.hostname = raw["hostname"]  # keep the last good hostname
    if raw["vendor"]:
        d.vendor = raw["vendor"]
    # Never regress a known type back to "unknown" (a scan that failed reverse-DNS
    # would otherwise wipe a device's classification).
    if raw["device_type"] and raw["device_type"] != "unknown":
        d.device_type = raw["device_type"]


async def _persist_scan(db: AsyncSession, result: dict, now: datetime) -> int:
    """Upsert scan results; mark missing devices offline. Returns NEW-row count.

    Identity handling beyond the two ARP quirks (MAC-less hosts coexist via
    mac=None; two IPs behind one MAC collapse to one row):
      * a host first seen MAC-less and later resolved to a MAC is UPGRADED in
        place (keeps the user's name/notes) instead of duplicated;
      * a MAC rotation (private-MAC / NIC change) at the same IP carries the
        user's name/notes onto the new row and drops the stale duplicate;
      * a recycled DHCP IP that now belongs to a DIFFERENT device resets that
        row's user metadata instead of mislabelling the new device.
    """
    rows = list((await db.execute(select(DeviceORM))).scalars().all())
    by_mac = {d.mac: d for d in rows if d.mac}
    by_ip_macless = {d.ip: d for d in rows if not d.mac}
    matched: set[int] = set()
    created_by_ip: dict[str, DeviceORM] = {}
    new_count = 0

    for raw in result["devices"]:
        mac = raw["mac"] or None
        macless_at_ip = by_ip_macless.get(raw["ip"])
        macless_free = macless_at_ip is not None and id(macless_at_ip) not in matched

        if mac and mac in by_mac:
            d = by_mac[mac]  # same device, matched by MAC
            _apply_scan_fields(d, raw, now)
            matched.add(id(d))
        elif mac and macless_free:
            # A previously MAC-less row at this IP is now resolved to a MAC.
            d = macless_at_ip
            d.mac = mac
            _apply_scan_fields(d, raw, now)
            by_mac[mac] = d
            matched.add(id(d))
        elif not mac and macless_free:
            d = macless_at_ip
            if (
                (d.custom_name or d.notes)
                and raw["hostname"]
                and not _same_identity(d.hostname, d.vendor, raw["hostname"], raw["vendor"])
            ):
                # A different device now holds this recycled IP — fresh identity.
                d.custom_name = ""
                d.notes = ""
                d.first_seen = now
            _apply_scan_fields(d, raw, now)
            matched.add(id(d))
        else:
            d = DeviceORM(
                ip=raw["ip"],
                mac=mac,  # None (not "") so multiple MAC-less hosts coexist
                hostname=raw["hostname"] or "",
                vendor=raw["vendor"] or "",
                device_type=raw["device_type"],
                is_online=True,
                first_seen=now,
                last_seen=now,
            )
            db.add(d)
            new_count += 1
            created_by_ip[raw["ip"]] = d
            if mac:
                by_mac[mac] = d

    for d in rows:
        if id(d) in matched:
            continue
        superseder = created_by_ip.get(d.ip)
        if (
            superseder is not None
            and superseder is not d
            and _same_identity(d.hostname, d.vendor, superseder.hostname, superseder.vendor)
        ):
            # Same device came back with a new MAC at this IP: move the user's
            # edits onto the live row and drop this stale duplicate.
            if d.custom_name and not superseder.custom_name:
                superseder.custom_name = d.custom_name
            if d.notes and not superseder.notes:
                superseder.notes = d.notes
            if d.first_seen:  # the old row predates this scan, so keep its first_seen
                superseder.first_seen = d.first_seen
            await db.delete(d)
        else:
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
        # Offload the file write so it can't block the event loop on slow storage.
        await asyncio.to_thread(adaptive_persistence.save_to_disk)


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
    task = asyncio.create_task(_run_scan_bg(target))
    _bg_tasks.add(task)
    task.add_done_callback(_reap_scan_task)
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
