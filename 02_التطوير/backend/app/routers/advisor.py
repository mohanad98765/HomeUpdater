"""AI Advisor endpoints — agentic Claude review of the network's update posture."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..services import advisor

router = APIRouter()


class AnalyzeRequest(BaseModel):
    lang: str = "en"


class KeyRequest(BaseModel):
    key: str = ""


@router.get("/status")
async def status() -> dict:
    """Whether the advisor is usable (an Anthropic API key is configured).

    ``env`` is true when the key comes from the environment/config (read-only in
    the UI); otherwise the UI may set/replace the encrypted-at-rest key.
    """
    return {
        "configured": advisor.is_configured(),
        "model": settings.advisor_model,
        "env": bool(settings.anthropic_api_key.strip()),
    }


@router.post("/key")
async def set_key(body: KeyRequest) -> dict:
    """Store the Anthropic API key (encrypted at rest), or clear it when blank.

    Rejected when the key is pinned via the environment (nothing to override)."""
    if settings.anthropic_api_key.strip():
        raise HTTPException(status_code=409, detail="API key is set via the environment.")
    advisor.set_api_key(body.key)
    return {"configured": advisor.is_configured()}


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Run the agentic advisor and return its prioritized recommendations."""
    try:
        return await advisor.analyze(db, lang_hint=body.lang)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
