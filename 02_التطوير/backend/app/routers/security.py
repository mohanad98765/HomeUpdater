"""Security endpoints — known vulnerabilities (CVEs) per device vendor via NVD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import HUB_DEVICE_ID, DeviceORM, InstalledSoftwareORM
from ..services import cpe, cve

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


# ===================================================================
# PRECISE matching — product + version via CPE, not a vendor keyword
# ===================================================================
@router.get("/precise")
async def precise_findings(
    db: AsyncSession = Depends(get_db),
    refresh_nvd: bool = Query(default=False, description="Query NVD for unmapped-cache entries"),
) -> dict:
    """CVEs that apply to the INSTALLED version of each inventoried product.

    Unlike ``/overview`` (vendor keyword -> indicative), this asks NVD whether the
    exact installed version is affected, and returns the version range that made
    each CVE apply so a reader can audit the claim.

    Products the curated CPE map does not cover, or whose reported version is not
    comparable, are returned under ``unmatched`` WITH a reason — never quietly
    downgraded to a keyword guess and presented as precise.
    """
    rows = (
        (
            await db.execute(
                select(InstalledSoftwareORM).where(InstalledSoftwareORM.device_id == HUB_DEVICE_ID)
            )
        )
        .scalars()
        .all()
    )

    matched: list[dict] = []
    unmatched: list[dict] = []
    for row in rows:
        identity = cpe.resolve(row.product_id, row.version, row.name)
        if identity is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    "name": row.name,
                    "version": row.version,
                    "reason": cpe.unmatched_reason(row.product_id, row.version, row.name),
                    # Why there is no coverage, when we investigated and know.
                    "detail": cpe.exclusion_detail(row.product_id, row.name),
                }
            )
            continue

        cached = await cve.get_cached(identity.cpe_name, db)
        if cached is None and refresh_nvd:
            try:
                cached = await cve.lookup_by_cpe(identity, db)
            except cve.CVEError as exc:
                unmatched.append(
                    {
                        "product_id": row.product_id,
                        "name": row.name,
                        "version": row.version,
                        "reason": f"nvd_unavailable: {exc}",
                    }
                )
                continue
        if cached is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    "name": row.name,
                    "version": row.version,
                    "reason": "not_yet_checked",
                }
            )
            continue

        entry = cpe.entry_for(row.product_id, row.name)
        cves = cached.get("cves", [])
        # Re-judged on every read (not from the cached 'precision'), so a cache written
        # before this rule existed is corrected without waiting for a 24h TTL.
        counted, uncounted = cve.counted_and_uncounted(cves, identity.version)
        matched.append(
            {
                "product_id": row.product_id,
                "name": row.name,
                "version": identity.version,
                "reported_version": row.version,  # before trimming, so the trim is visible
                "cpe_name": identity.cpe_name,
                "confidence": entry.confidence if entry else "",
                "caveat": entry.caveat if entry else "",
                "total_results": cached.get("total_results", 0),
                # Split by how defensible each hit is: a record that matches every
                # version, names our product as a non-vulnerable platform, or bounds
                # it on a date scheme is NOT evidence about this build.
                "cves": counted,
                "broad_matches": uncounted,
                "fetched_at": cached.get("fetched_at"),
            }
        )

    return {
        "match_mode": "cpe",
        "matched": matched,
        "unmatched": unmatched,
        "coverage": cpe.coverage([(r.product_id, r.name) for r in rows]),
    }
