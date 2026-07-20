"""Security endpoints — known vulnerabilities (CVEs) per device vendor via NVD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import DeviceORM
from ..services import cve

router = APIRouter()

_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _top_severity(cves: list[dict]) -> str:
    best, best_rank = "", 0
    for c in cves:
        rank = _SEV_RANK.get(c.get("severity", ""), 0)
        if rank > best_rank:
            best, best_rank = c.get("severity", ""), rank
    return best


@router.get("/cves")
async def get_cves(
    keyword: str = Query(..., min_length=1),
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """CVE summary for a vendor keyword (24h cached; fetches from NVD if stale)."""
    try:
        return await cve.lookup_cves(keyword, db, force=force)
    except cve.CVEError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)) -> dict:
    """Per-device vendor CVE summary — from cache only (no NVD calls, instant)."""
    devices = (await db.execute(select(DeviceORM))).scalars().all()
    items: list[dict] = []
    vendors: set[str] = set()
    checked: set[str] = set()
    for d in devices:
        vendor = (d.vendor or "").strip()
        entry = {
            "device_id": d.id,
            "display_name": d.custom_name or d.hostname or d.vendor or d.ip,
            "ip": d.ip,
            "vendor": vendor,
            "cve_total": None,
            "top_severity": None,
            "top_cve": None,
            "top_cve_url": None,
            "checked": False,
        }
        if vendor:
            vendors.add(vendor)
            cached = await cve.get_cached(vendor, db)
            if cached:
                checked.add(vendor)
                cves = cached.get("cves") or []
                entry["cve_total"] = cached["total_results"]
                entry["top_severity"] = _top_severity(cves)
                # The list is stored most-severe-first, so cves[0] is the top CVE.
                if cves:
                    top = cves[0]
                    cid = top.get("id") or None
                    entry["top_cve"] = cid
                    entry["top_cve_url"] = top.get("url") or (
                        f"https://nvd.nist.gov/vuln/detail/{cid}" if cid else None
                    )
                entry["checked"] = True
        items.append(entry)
    return {
        "devices": items,
        "vendors_total": len(vendors),
        "vendors_checked": len(checked),
    }


@router.post("/refresh")
async def refresh(db: AsyncSession = Depends(get_db)) -> dict:
    """Fetch CVEs for every distinct device vendor (throttled for NVD's limits)."""
    devices = (await db.execute(select(DeviceORM))).scalars().all()
    vendors = sorted({(d.vendor or "").strip() for d in devices if (d.vendor or "").strip()})
    logger.info(f"CVE refresh for {len(vendors)} vendor(s)")
    return await cve.refresh_vendors(vendors, db)
