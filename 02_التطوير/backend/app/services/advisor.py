"""AI Advisor — an *agentic* Claude loop that reviews the home network's update
posture and recommends a prioritized action plan.

This is HomeUpdater's agentic-AI feature. Claude is given three local, read-only
tools (list devices, check known vulnerabilities, list pending updates) and
decides which to call to build the picture, then writes a short, prioritized,
plain-language plan. Nothing leaves the machine except the compact summaries the
model asks for — the tools run entirely against the local database.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.orm import DeviceORM, SoftwarePackageORM, WindowsUpdateORM
from ..services import cve


class AdvisorError(Exception):
    """Raised when the advisor can't run (not configured, or the API failed)."""


_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def is_configured() -> bool:
    """True when an Anthropic API key is set (feature is usable)."""
    return bool(settings.anthropic_api_key.strip())


# --------------------------------------------------------------------------- #
# Local tools the agent may call — all read-only, all against the local DB.    #
# --------------------------------------------------------------------------- #
async def _tool_list_devices(db: AsyncSession) -> dict:
    rows = (await db.execute(select(DeviceORM))).scalars().all()
    devices = [
        {
            "id": d.id,
            "name": d.custom_name or d.hostname or d.vendor or d.ip,
            "ip": d.ip,
            "vendor": d.vendor or "unknown",
            "type": d.device_type,
            "online": d.is_online,
        }
        for d in rows
    ]
    return {"total": len(devices), "devices": devices}


async def _tool_check_vulnerabilities(db: AsyncSession) -> dict:
    rows = (await db.execute(select(DeviceORM))).scalars().all()
    flagged: list[dict] = []
    for d in rows:
        vendor = (d.vendor or "").strip()
        if not vendor:
            continue
        cached = await cve.get_cached(vendor, db)
        if not cached or cached["total_results"] <= 0:
            continue
        top, best = "", 0
        for c in cached["cves"]:
            rank = _SEV_RANK.get(c.get("severity", ""), 0)
            if rank > best:
                best, top = rank, c.get("severity", "")
        flagged.append(
            {
                "device": d.custom_name or d.hostname or d.ip,
                "vendor": vendor,
                "known_vulnerabilities": cached["total_results"],
                "top_severity": top or "UNKNOWN",
            }
        )
    flagged.sort(
        key=lambda x: (_SEV_RANK.get(x["top_severity"], 0), x["known_vulnerabilities"]),
        reverse=True,
    )
    return {
        "flagged_count": len(flagged),
        "devices": flagged,
        "note": (
            "Matched by device vendor from cached NVD data. An empty list can mean "
            "the vendors are clean OR that no security scan has been run yet."
        ),
    }


async def _tool_list_pending_updates(db: AsyncSession) -> dict:
    apps = (
        await db.execute(
            select(SoftwarePackageORM).where(SoftwarePackageORM.is_installed.is_(False))
        )
    ).scalars().all()
    app_items = [
        {"name": a.name or a.package_id, "current": a.current_version, "available": a.available_version}
        for a in apps
        if a.available_version
    ]
    win = (
        await db.execute(
            select(WindowsUpdateORM).where(WindowsUpdateORM.is_installed.is_(False))
        )
    ).scalars().all()
    win_items = [{"title": w.title, "severity": w.severity, "kind": w.kind} for w in win]
    return {
        "app_updates": {"total": len(app_items), "items": app_items[:40]},
        "windows_updates": {"total": len(win_items), "items": win_items[:40]},
    }


_TOOLS = [
    {
        "name": "list_devices",
        "description": (
            "List every device discovered on the home network (name, IP, vendor, type, "
            "online status). Call this first to see what is on the network."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_vulnerabilities",
        "description": (
            "List devices that have known security vulnerabilities (CVEs), matched by "
            "vendor from the local NVD cache, sorted by severity. Use this to find the "
            "riskiest devices."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_pending_updates",
        "description": (
            "List pending software/app updates (winget) and pending Windows updates on "
            "this PC, with versions and severity."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

_DISPATCH = {
    "list_devices": _tool_list_devices,
    "check_vulnerabilities": _tool_check_vulnerabilities,
    "list_pending_updates": _tool_list_pending_updates,
}

_SYSTEM = """You are the AI Advisor inside HomeUpdater, a local app that keeps a home \
network's devices up to date. Your job: review the network's update posture and give the \
user a short, prioritized action plan in plain language.

Use the tools to gather the picture — what devices exist, which have known \
vulnerabilities, and what updates are pending. Then recommend what to update FIRST and \
why, ordered by risk: a router or PC carrying a CRITICAL/HIGH CVE outranks a low-risk app \
update. Be concrete and concise; prefer a short numbered list over prose. If the network \
has not been scanned yet (no devices, or no data at all), say so plainly and tell the \
user to run a network scan first.

Reply in the SAME language the user writes in (Arabic or English)."""


async def analyze(db: AsyncSession, lang_hint: str = "en") -> dict:
    """Run the agentic advisor loop.

    Returns ``{"recommendations": str, "trace": [{"tool": name}, ...], "model": str}``.
    Raises :class:`AdvisorError` if the key is missing or the API call fails.
    """
    if not is_configured():
        raise AdvisorError("AI Advisor is not configured (no Anthropic API key).")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    ar = lang_hint.startswith("ar")
    user_msg = (
        "Review my home network's update posture and give me a prioritized action plan: "
        "what should I update first, and why? "
        + ("Respond in Arabic." if ar else "Respond in English.")
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    trace: list[dict] = []

    try:
        for _ in range(8):  # cap the agentic loop
            resp = await client.messages.create(
                model=settings.advisor_model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return {"recommendations": text, "trace": trace, "model": resp.model}

            # Echo the assistant turn back verbatim (thinking + tool_use blocks),
            # then answer every tool_use with a tool_result in one user turn.
            messages.append({"role": "assistant", "content": resp.content})
            results: list[dict] = []
            for block in resp.content:
                if block.type == "tool_use":
                    trace.append({"tool": block.name})
                    fn = _DISPATCH.get(block.name)
                    try:
                        data = await fn(db) if fn else {"error": f"unknown tool {block.name}"}
                    except Exception as exc:  # surface tool failure to the model
                        logger.warning(f"Advisor tool {block.name} failed: {exc}")
                        data = {"error": str(exc)}
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(data, ensure_ascii=False),
                        }
                    )
            messages.append({"role": "user", "content": results})

        raise AdvisorError("Advisor did not converge (too many tool rounds).")
    except anthropic.APIError as exc:
        logger.error(f"Advisor API error: {exc}")
        raise AdvisorError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
