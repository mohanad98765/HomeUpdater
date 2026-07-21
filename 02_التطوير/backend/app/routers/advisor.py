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


class ConsentRequest(BaseModel):
    consented: bool = False


# T11 — data-sharing consent shown before the first cloud call. Presented by the
# UI; the backend refuses the cloud calls (403) until the user accepts it.
_CONSENT_TEXT_AR = (
    "يعمل «المستشار الذكي» عبر واجهة Anthropic (Claude) السحابية. عند تشغيله تُرسَل "
    "ملخّصات عن شبكتك المنزلية — أسماء الأجهزة وعناوين IP والمورّدين وأنواع الأجهزة "
    "وعدّاد الثغرات (CVE) وقائمة التحديثات المعلّقة — إلى خوادم Anthropic لتحليلها. "
    "لا تُرسَل كلمات مرورك ولا بيانات اعتماد SSH/WinRM/Home Assistant ولا محتوى ملفاتك. "
    "التوصيات اجتهادية (best-effort) بلا ضمان، ولا يُطبَّق أي تحديث إلا بموافقتك الصريحة "
    "عبر زر «تطبيق». أنت وحدك مسؤول عن الأجهزة التي تأذن بتحديثها. تخضع معالجة البيانات "
    "لشروط خصوصية Anthropic التجارية (لا تُستخدم مدخلات الـ API للتدريب). يمكنك سحب "
    "الموافقة في أي وقت من الإعدادات، ولن يعمل المستشار بعدها حتى تُعيد الموافقة."
)
_CONSENT_TEXT_EN = (
    "The AI Advisor runs via Anthropic's (Claude) cloud API. When you use it, "
    "summaries of your home network — device names, IPs, vendors, device types, "
    "vulnerability (CVE) counts and the list of pending updates — are sent to "
    "Anthropic for analysis. Your passwords, SSH/WinRM/Home Assistant credentials "
    "and file contents are NOT sent. Recommendations are best-effort with no "
    "warranty, and no update is applied without your explicit approval via the "
    "Apply button; you alone are responsible for the devices you authorize to "
    "update. Processing is governed by Anthropic's commercial privacy terms (API "
    "inputs are not used for training). You may withdraw consent anytime in "
    "Settings, after which the Advisor stops working until you re-consent."
)


def _require_consent() -> None:
    if not advisor.has_consent():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "consent_required",
                "message_ar": _CONSENT_TEXT_AR,
                "message_en": _CONSENT_TEXT_EN,
            },
        )


@router.get("/status")
async def status() -> dict:
    """Whether the advisor is usable (an Anthropic API key is configured).

    ``env`` is true when the key comes from the environment/config (read-only in
    the UI); otherwise the UI may set/replace the encrypted-at-rest key.
    ``consented`` reflects the T11 data-sharing consent (required to run)."""
    return {
        "configured": advisor.is_configured(),
        "model": settings.advisor_model,
        "env": bool(settings.anthropic_api_key.strip()),
        "consented": advisor.has_consent(),
    }


@router.get("/consent-text")
async def consent_text() -> dict:
    """The consent statement the UI shows before the first cloud call."""
    return {"ar": _CONSENT_TEXT_AR, "en": _CONSENT_TEXT_EN, "consented": advisor.has_consent()}


@router.post("/consent")
async def consent(body: ConsentRequest) -> dict:
    """Record (or revoke) consent to send local network summaries to the API."""
    if body.consented:
        advisor.record_consent()
    else:
        advisor.revoke_consent()
    return {"consented": advisor.has_consent()}


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
    _require_consent()
    try:
        return await advisor.analyze(db, lang_hint=body.lang)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/chat")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Conversational Q&A about the network (read-only advisor tools)."""
    _require_consent()
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
