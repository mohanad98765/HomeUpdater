"""Evidence Pack + license endpoints.

The pack is the paid artifact, so its export is the ONE thing gated by a license.
Everything else in the app — scanning, patching, precise matching, viewing findings
on screen — stays free on purpose: matching a free competitor on the commodity and
charging for the document is the whole pricing idea.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services import audit, evidence, licensing, rollup

router = APIRouter()


# ===================================================================
# License
# ===================================================================
class ActivateBody(BaseModel):
    key: str = Field(..., min_length=8, max_length=4096)


@router.get("/license")
async def license_status() -> dict:
    """The stored license, re-verified on every read (disk is never trusted)."""
    return licensing.load().to_dict()


@router.post("/license/activate")
async def activate(body: ActivateBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Verify a key's signature and store it. An invalid key is never persisted."""
    try:
        lic = licensing.save(body.key)
    except licensing.LicenseError as exc:
        # The failure reason is recorded too: a run of bad-key attempts is itself
        # something an owner may want to see.
        await audit.record_safe(
            db, "license_activate", actor="user", outcome="denied", detail={"reason": str(exc)}
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit.record_safe(
        db,
        "license_activate",
        actor="user",
        detail={"tier": lic.tier, "licensee": lic.licensee, "key_id": lic.key_id},
    )
    return lic.to_dict()


@router.post("/license/clear")
async def clear_license(db: AsyncSession = Depends(get_db)) -> dict:
    licensing.clear()
    await audit.record_safe(db, "license_clear", actor="user")
    return {"ok": True}


# ===================================================================
# Evidence Pack
# ===================================================================
@router.get("/pack")
async def pack(db: AsyncSession = Depends(get_db)) -> dict:
    """The full pack as JSON, hash-stamped. Requires a paid tier."""
    try:
        lic = licensing.require_evidence_export()
    except licensing.LicenseError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc  # 402 = payment required
    built = await evidence.build(db, licensee=lic.licensee)
    logger.info(f"evidence pack issued: stamp={built['content_sha256'][:12]}…")
    await audit.record_safe(
        db,
        "evidence_export",
        actor="user",
        target="this-pc",
        detail={
            "format": "json",
            "stamp": built["content_sha256"],
            "findings": built["pack"]["findings_total"],
            "chain_ok": built["pack"]["audit"]["chain_ok"],
        },
    )
    return built


@router.get("/pack.json")
async def pack_canonical(db: AsyncSession = Depends(get_db)) -> Response:
    """The pack as the EXACT bytes the content stamp is computed over.

    The printed document tells the reader to hash the JSON file and compare it with the
    stamp. That instruction was not performable on anything the product produced: the
    stamp covers ``audit.canonical(body)`` — sorted keys, tight separators, the inner
    pack object only — while the UI downloaded ``JSON.stringify(response, null, 2)`` of
    the whole envelope. Three different byte sequences, one of which the reader was told
    to check.

    This endpoint serves the bytes that were hashed. An instruction a reader cannot
    carry out is worse than no instruction: it invites them to conclude the pack has
    been tampered with.
    """
    try:
        lic = licensing.require_evidence_export()
    except licensing.LicenseError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    built = await evidence.build(db, licensee=lic.licensee)
    body = audit.canonical(built["pack"]).encode("utf-8")
    await audit.record_safe(
        db,
        "evidence_export",
        actor="user",
        target="this-pc",
        detail={"format": "json-canonical", "stamp": built["content_sha256"]},
    )
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="homeupdater-evidence.json"',
            # So a reader can check the file they hold without opening the document.
            "X-Content-SHA256": built["content_sha256"],
        },
    )


@router.get("/pack.csv")
async def pack_csv(db: AsyncSession = Depends(get_db)) -> Response:
    """The findings table as CSV — the form a reviewer actually works in."""
    try:
        lic = licensing.require_evidence_export()
    except licensing.LicenseError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    built = await evidence.build(db, licensee=lic.licensee)
    await audit.record_safe(
        db,
        "evidence_export",
        actor="user",
        target="this-pc",
        detail={"format": "csv", "stamp": built["content_sha256"]},
    )
    # utf-8-sig so Excel on an Arabic Windows opens it without mangling the text.
    return Response(
        content=evidence.to_csv(built).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="homeupdater-evidence.csv"'},
    )


@router.get("/pack.html")
async def pack_html(db: AsyncSession = Depends(get_db)) -> Response:
    """The pack as a print-ready document — what an auditor is handed.

    Not a generated PDF on purpose: the build ships no PDF engine and no Arabic font,
    and a PDF with broken Arabic shaping would be worse than none. This document opens
    in any browser (including the app's own WebView2), shapes Arabic correctly, and
    prints to PDF in one step.
    """
    try:
        lic = licensing.require_evidence_export()
    except licensing.LicenseError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    built = await evidence.build(db, licensee=lic.licensee)
    await audit.record_safe(
        db,
        "evidence_export",
        actor="user",
        target="this-pc",
        detail={"format": "html", "stamp": built["content_sha256"]},
    )
    return Response(
        content=evidence.to_html(built).encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="homeupdater-evidence.html"'},
    )


@router.get("/preview")
async def preview(db: AsyncSession = Depends(get_db)) -> dict:
    """What the pack WOULD contain — free, so the value is visible before paying.

    Counts and integrity status only; no per-CVE detail and no stamp, which is
    exactly what the paid artifact adds.
    """
    built = await evidence.build(db)
    body = built["pack"]
    return {
        "inventory_total": body["inventory_total"],
        "coverage": body["coverage"],
        "findings_total": body["findings_total"],
        "broad_matches_total": body["broad_matches_total"],
        "unmatched_total": len(body["unmatched"]),
        "audit": body["audit"],
        "licensed": licensing.load().to_dict()["can_export_evidence"],
    }


# ===================================================================
# Partner roll-up — many sites, no cloud console
# ===================================================================
class RollupBody(BaseModel):
    """Evidence packs exactly as each site exported them (JSON, unmodified)."""

    packs: list[dict] = Field(default_factory=list, max_length=500)


def _require_partner() -> licensing.License:
    lic = licensing.load()
    d = lic.to_dict()
    if not d["can_export_evidence"] or lic.tier != "partner":
        raise HTTPException(
            status_code=402,
            detail=(
                "partner_tier_required"
                if d["can_export_evidence"]
                else (d["reason"] or "not_licensed")
            ),
        )
    return lic


@router.post("/rollup")
async def build_rollup(body: RollupBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Aggregate site packs. Each is re-hashed; an altered pack is REJECTED, not blended.

    Partner tier only — this is the multi-site view a reseller buys.
    """
    _require_partner()
    result = rollup.build(body.packs)
    await audit.record_safe(
        db,
        "rollup_build",
        actor="user",
        detail={
            "sites_verified": result["totals"]["sites_verified"],
            "sites_rejected": result["totals"]["sites_rejected"],
        },
    )
    return result


@router.post("/rollup.csv")
async def rollup_csv(body: RollupBody, db: AsyncSession = Depends(get_db)) -> Response:
    _require_partner()
    result = rollup.build(body.packs)
    await audit.record_safe(
        db, "rollup_build", actor="user", detail={"format": "csv", **result["totals"]}
    )
    return Response(
        content=rollup.to_csv(result).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="homeupdater-rollup.csv"'},
    )
