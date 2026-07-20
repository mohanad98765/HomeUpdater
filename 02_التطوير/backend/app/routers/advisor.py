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


@router.get("/status")
async def status() -> dict:
    """Whether the advisor is usable (an Anthropic API key is configured)."""
    return {"configured": advisor.is_configured(), "model": settings.advisor_model}


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Run the agentic advisor and return its prioritized recommendations."""
    try:
        return await advisor.analyze(db, lang_hint=body.lang)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
