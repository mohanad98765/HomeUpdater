"""AI Advisor endpoints — agentic Claude review of the network's update posture."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..services import advisor
from ..services.update_progress import update_progress

router = APIRouter()

# Strong refs to in-flight apply tasks so they aren't GC'd, and so a closed
# WebView2 window (client disconnect) can't cancel a half-finished install.
_apply_tasks: set[asyncio.Task] = set()


async def _run_apply_bg(actions: list[dict]) -> dict:
    """Run the plan on its OWN DB session and release the update slot when done —
    NOT tied to the request, so a client disconnect can't strand a partial install
    or leak the slot."""
    try:
        async with SessionLocal() as db:
            return await advisor.apply_plan(db, actions)
    finally:
        update_progress.release()


class AnalyzeRequest(BaseModel):
    lang: str = "en"


class KeyRequest(BaseModel):
    key: str = ""


class ActionItem(BaseModel):
    type: str
    id: str
    title: str = ""
    reason: str = ""


class ApplyRequest(BaseModel):
    actions: list[ActionItem] = []


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []


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


@router.post("/chat")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Conversational Q&A about the network (read-only advisor tools)."""
    if not body.messages:
        raise HTTPException(status_code=400, detail="No message.")
    try:
        return await advisor.chat(db, [m.model_dump() for m in body.messages])
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/apply")
async def apply(body: ApplyRequest) -> dict:
    """Apply the advisor's plan — installs ONLY pending updates (validated in the
    service). Shares the single update slot so it can't race the Updates page.

    The install runs as a background task with its own DB session; we shield-await
    it so the response is unchanged for a connected client, but if the window is
    closed mid-install the task keeps running to completion and releases the slot
    itself (no partial install, no wedged 409 gate)."""
    actions = [a.model_dump() for a in body.actions][:10]
    if not actions:
        raise HTTPException(status_code=400, detail="No actions to apply.")
    if not update_progress.try_claim("install"):
        raise HTTPException(status_code=409, detail="Another update operation is running.")
    task = asyncio.create_task(_run_apply_bg(actions))
    _apply_tasks.add(task)
    task.add_done_callback(_apply_tasks.discard)
    return await asyncio.shield(task)
