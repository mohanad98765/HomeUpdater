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
from ..services import audit, evidence, licensing

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
