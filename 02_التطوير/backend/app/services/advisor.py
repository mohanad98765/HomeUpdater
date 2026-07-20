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

from .. import crypto
from ..config import get_data_dir, settings
from ..models.orm import DeviceORM, SoftwarePackageORM, WindowsUpdateORM
from ..services import cve


class AdvisorError(Exception):
    """Raised when the advisor can't run (not configured, or the API failed)."""


_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_KEY_FILE = "advisor_key.enc"


def get_api_key() -> str:
    """Return the Anthropic API key: env/config first, else the encrypted file.

    The UI-saved key is stored ENCRYPTED at rest (Fernet + DPAPI, same as SSH/
    WinRM/HA credentials — see crypto.py), never in plaintext.
    """
    env = settings.anthropic_api_key.strip()
    if env:
        return env
    path = get_data_dir() / _KEY_FILE
    if path.exists():
        try:
            return crypto.decrypt(path.read_text(encoding="utf-8").strip())
        except Exception as exc:  # noqa: BLE001 — bad/foreign key file → treat as unset
            logger.warning(f"Advisor key could not be decrypted: {exc}")
    return ""


def set_api_key(key: str) -> None:
    """Persist the API key encrypted (or clear it when ``key`` is blank)."""
    path = get_data_dir() / _KEY_FILE
    key = (key or "").strip()
    if not key:
        path.unlink(missing_ok=True)
        return
    path.write_text(crypto.encrypt(key), encoding="utf-8")


def is_configured() -> bool:
    """True when an Anthropic API key is available (feature is usable)."""
    return bool(get_api_key())


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
    # Cap the payload so a very large network can't blow up the token budget.
    return {"total": len(devices), "devices": devices[:80]}


async def _tool_check_vulnerabilities(db: AsyncSession) -> dict:
    rows = (await db.execute(select(DeviceORM))).scalars().all()
    flagged: list[dict] = []
    for d in rows:
        vendor = (d.vendor or "").strip()
        if not vendor:
            continue
        try:
            cached = await cve.get_cached(vendor, db)
        except Exception as exc:  # one bad/corrupt cache row must not kill the whole tool
            logger.warning(f"CVE cache read failed for {vendor!r}: {exc}")
            continue
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
        "devices": flagged[:60],
        "note": (
            "Matched by device vendor from cached NVD data. An empty list can mean "
            "the vendors are clean OR that no security scan has been run yet."
        ),
    }


async def _tool_list_pending_updates(db: AsyncSession) -> dict:
    apps = (
        (
            await db.execute(
                select(SoftwarePackageORM).where(SoftwarePackageORM.is_installed.is_(False))
            )
        )
        .scalars()
        .all()
    )
    app_items = [
        {
            "id": a.package_id,  # exact id to cite in set_plan (type="app")
            "name": a.name or a.package_id,
            "current": a.current_version,
            "available": a.available_version,
        }
        for a in apps
        if a.available_version
    ]
    win = (
        (await db.execute(select(WindowsUpdateORM).where(WindowsUpdateORM.is_installed.is_(False))))
        .scalars()
        .all()
    )
    win_items = [
        {"id": w.update_id, "title": w.title, "severity": w.severity, "kind": w.kind} for w in win
    ]
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
            "this PC, each with an exact `id`, versions and severity."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_plan",
        "description": (
            "Record the final prioritized, APPLICABLE update plan — the specific pending "
            "updates the user should apply, most important first. Include ONLY items whose "
            "exact `id` appeared in list_pending_updates output (local app/Windows updates). "
            "Do NOT include remote Linux, remote-Windows, or Home Assistant items here — "
            "mention those in your text summary only. Call this once, before the summary; "
            "skip it entirely if there are no applicable local updates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["app", "windows"]},
                            "id": {
                                "type": "string",
                                "description": "exact package_id (app) or update_id (windows) from list_pending_updates output",  # noqa: E501
                            },
                            "title": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["type", "id", "title"],
                    },
                }
            },
            "required": ["actions"],
        },
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

When there ARE pending local app or Windows updates, call set_plan once with the top \
applicable items (most important first, using the exact ids from list_pending_updates) so \
the user can apply them with one click — then write your text summary.

Reply in the SAME language the user writes in (Arabic or English)."""


async def analyze(db: AsyncSession, lang_hint: str = "en") -> dict:
    """Run the agentic advisor loop.

    Returns ``{"recommendations": str, "trace": [{"tool": name}, ...], "model": str}``.
    Raises :class:`AdvisorError` if the key is missing or the API call fails.
    """
    api_key = get_api_key()
    if not api_key:
        raise AdvisorError("AI Advisor is not configured (no Anthropic API key).")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    ar = lang_hint.startswith("ar")
    user_msg = (
        "Review my home network's update posture and give me a prioritized action plan: "
        "what should I update first, and why? "
        + ("Respond in Arabic." if ar else "Respond in English.")
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    trace: list[dict] = []
    plan: list[dict] = []  # structured applicable actions from the set_plan tool

    try:
        for _ in range(8):  # cap the agentic loop
            resp = await client.messages.create(
                model=settings.advisor_model,
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                # Distinguish a real answer from a safety refusal or a truncation —
                # otherwise both would surface as a blank/half-written "success".
                if resp.stop_reason == "refusal":
                    raise AdvisorError("The model declined this request. Try rephrasing.")
                if not text:
                    raise AdvisorError("The model returned an empty answer; please try again.")
                return {
                    "recommendations": text,
                    "trace": trace,
                    "model": resp.model,
                    "truncated": resp.stop_reason == "max_tokens",
                    "actions": plan[:10],
                }

            # Echo the assistant turn back verbatim (thinking + tool_use blocks),
            # then answer every tool_use with a tool_result in one user turn.
            messages.append({"role": "assistant", "content": resp.content})
            results: list[dict] = []
            for block in resp.content:
                if block.type == "tool_use":
                    trace.append({"tool": block.name})
                    if block.name == "set_plan":
                        # Terminal tool: capture the applicable plan; don't hit the DB.
                        raw = (
                            block.input.get("actions", []) if isinstance(block.input, dict) else []
                        )
                        plan = [a for a in raw if isinstance(a, dict) and a.get("id")]
                        data = {"recorded": len(plan)}
                    else:
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


async def apply_plan(db: AsyncSession, actions: list[dict]) -> dict:
    """Apply the advisor's plan — but ONLY updates that are genuinely pending.

    Safety gate: every requested id is validated against the pending rows in the
    DB before anything runs, so the model can only ever trigger the install of an
    update that is already pending on this machine (the same set the user could
    apply from the Updates page). Unknown/stale ids are skipped, not installed.
    """
    from . import software_updates, windows_updates

    want_app = [str(a["id"]) for a in actions if a.get("type") == "app" and a.get("id")]
    want_win = [str(a["id"]) for a in actions if a.get("type") == "windows" and a.get("id")]

    valid_app: list[str] = []
    if want_app:
        rows = (
            (
                await db.execute(
                    select(SoftwarePackageORM).where(
                        SoftwarePackageORM.package_id.in_(want_app),
                        SoftwarePackageORM.is_installed.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        valid_app = [r.package_id for r in rows]

    valid_win: list[str] = []
    if want_win:
        rows = (
            (
                await db.execute(
                    select(WindowsUpdateORM).where(
                        WindowsUpdateORM.update_id.in_(want_win),
                        WindowsUpdateORM.is_installed.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        valid_win = [r.update_id for r in rows]

    valid = set(valid_app) | set(valid_win)
    skipped = [i for i in (want_app + want_win) if i not in valid]

    app_res = None
    if valid_app:
        try:
            app_res = await software_updates.install_many(valid_app)
        except Exception as exc:  # e.g. winget unavailable — report, don't 500
            logger.error(f"Advisor apply (apps) failed: {exc}")
            app_res = {"installed": 0, "total": len(valid_app), "error": str(exc)}

    win_res = None
    if valid_win:
        try:
            win_res = await windows_updates.install_updates(valid_win)
        except Exception as exc:  # WUA can raise on hard failure
            logger.error(f"Advisor apply (windows) failed: {exc}")
            win_res = {"installed": 0, "total": len(valid_win), "error": str(exc)}

    # Persist installed=True for succeeded items (mirrors the Updates endpoints),
    # so applied updates stop showing as pending and can't be re-triggered.
    async def _persist(model, id_field: str, results: list[dict], code_field: str) -> None:
        by_id = {r[id_field]: r for r in results if isinstance(r, dict) and r.get(id_field)}
        if not by_id:
            return
        rows = (
            (await db.execute(select(model).where(getattr(model, id_field).in_(list(by_id)))))
            .scalars()
            .all()
        )
        for row in rows:
            r = by_id.get(getattr(row, id_field))
            if r:
                row.install_result = r.get(code_field, 0)
                row.is_installed = bool(r.get("succeeded"))

    await _persist(
        SoftwarePackageORM, "package_id", (app_res or {}).get("results", []), "exit_code"
    )
    await _persist(WindowsUpdateORM, "update_id", (win_res or {}).get("results", []), "result_code")
    await db.commit()

    # "applied" = updates that actually SUCCEEDED, not merely attempted.
    applied = (app_res or {}).get("installed", 0) + (win_res or {}).get("installed", 0)
    return {"applied": applied, "app": app_res, "windows": win_res, "skipped": skipped}
