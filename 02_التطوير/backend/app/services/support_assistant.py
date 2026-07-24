"""In-app AI SUPPORT assistant — answers questions about how to USE HomeUpdater.

Distinct from services/advisor.py (which reasons over the local network DB):
this is a stateless, single-shot Q&A scoped strictly to the app's own features
and troubleshooting. It sends NO network data — only the user's typed question
and a static system prompt — so it needs no T11 network-data consent. It reuses
the advisor's stored Anthropic key, but runs under its OWN lock so a running
network analysis never blocks a help question (and vice-versa).
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from ..config import settings
from . import advisor

_REQUEST_TIMEOUT = 120.0  # per Claude API request (seconds)
_MAX_TURNS = 20  # trailing conversation turns kept
_MAX_TOKENS = 1024  # a help answer is short

# Own lock, independent of the advisor's — help stays usable during an analysis.
_support_lock = asyncio.Lock()


class SupportError(Exception):
    """Raised when the support assistant can't run (no key / API failure / busy)."""


_SUPPORT_SYSTEM = """You are the built-in help assistant for HomeUpdater (محدِّث المنزل), \
a LOCAL Windows desktop app that updates the devices on a home network. Answer ONLY \
questions about how to use HomeUpdater and how to fix problems inside it. If asked \
anything unrelated (general knowledge, coding, other software, world facts, personal \
questions), briefly say you can only help with HomeUpdater and invite a HomeUpdater \
question — do not answer the off-topic part. Never invent features. Reply in the SAME \
language as the user (Arabic or English), concisely and step by step.

What HomeUpdater does:
- Scans the local network and lists devices (Devices page). Everything is local; no cloud.
- Updates THIS PC: Windows Update, apps via winget, and drivers (Updates page — three tabs).
- Android: wireless updates over ADB with Android 11+ pairing (Android page).
- Linux hosts: updates over SSH with host-key verification (Linux page).
- Home Assistant: smart-home updates (Home Assistant page).
- Remote Windows PCs: updates over WinRM/winget (Windows Remote page).
- AI Advisor: an agentic assistant that reviews the network and recommends a priority \
plan; it needs an Anthropic API key and a one-time data-sharing consent, and applies \
updates only with the user's explicit permission.
- Security: known vulnerabilities (CVE) per device, plus a PDF report.
- Protected by a password set on first run; credentials are stored encrypted; 6 languages \
(Arabic RTL, English, French, Spanish, Turkish, Urdu).

Common fixes:
- "An update keeps failing / stays pending": some winget outcomes (reboot required, or \
already up to date) are normal, not failures; re-check after a reboot. A red 'failed' box \
shows the real error message — read it.
- "The AI Advisor asks for a key": open the Advisor page and paste an Anthropic API key; \
it is stored encrypted on the device.
- "SmartScreen warning on install": the installer is signed (self-signed for now) — choose \
More info → Run anyway.
- "A device isn't found": run a scan from the Devices page; some devices only answer on a \
second pass.
- "Remote Windows won't update": the target PC needs WinRM enabled and reachable, with an \
admin username and password.

Keep answers short. Never answer non-HomeUpdater questions."""


def is_configured() -> bool:
    """True when an Anthropic API key is available (shared with the advisor)."""
    return advisor.is_configured()


async def support_chat(history: list[dict]) -> dict:
    """Answer a HomeUpdater usage/troubleshooting question. Returns ``{reply, model}``.

    ``history`` is ``[{role:'user'|'assistant', content:str}, ...]`` with the
    newest user turn last. Stateless: no tools, no database, no network data sent.
    """
    api_key = advisor.get_api_key()
    if not api_key:
        raise SupportError("AI support is not configured (no Anthropic API key).")

    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": str(m["content"])}
        for m in history
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ][-_MAX_TURNS:]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)  # the API requires the conversation to start on a user turn
    if not messages:
        raise SupportError("Ask a question to start.")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT, max_retries=2)
    if _support_lock.locked():
        raise SupportError("المساعد مشغول بسؤال آخر — انتظر لحظة / Assistant is busy.")
    async with _support_lock:
        try:
            resp = await client.messages.create(
                model=settings.advisor_model,
                max_tokens=_MAX_TOKENS,
                system=_SUPPORT_SYSTEM,
                messages=messages,
            )
        except anthropic.APIError as exc:
            logger.error(f"Support assistant API error: {exc}")
            raise SupportError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc

    text = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise SupportError("The assistant returned an empty answer.")
    return {"reply": text, "model": getattr(resp, "model", settings.advisor_model)}
