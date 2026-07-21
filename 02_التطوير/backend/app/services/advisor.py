"""AI Advisor — an *agentic* Claude loop that reviews the home network's update
posture and recommends a prioritized action plan.

This is HomeUpdater's agentic-AI feature. Claude is given three local, read-only
tools (list devices, check known vulnerabilities, list pending updates) and
decides which to call to build the picture, then writes a short, prioritized,
plain-language plan. Nothing leaves the machine except the compact summaries the
model asks for — the tools run entirely against the local database.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..config import get_data_dir, settings
from ..models.orm import (
    DeviceORM,
    SoftwarePackageORM,
    SSHHostORM,
    WindowsUpdateORM,
    WinRMHostORM,
)
from ..services import cve


class AdvisorError(Exception):
    """Raised when the advisor can't run (not configured, or the API failed)."""


_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_KEY_FILE = "advisor_key.enc"

# Cost/latency guards for the (expensive) agentic calls.
_REQUEST_TIMEOUT = 120.0  # per Claude API request (seconds)
_AGENT_DEADLINE = 300.0  # whole tool-use loop across all rounds (seconds)
_MAX_ROUNDS = 8  # cap the agentic loop
# Serialize analyze/chat so repeated clicks can't stack parallel opus calls
# (each bounded above). A second concurrent request is rejected, not queued.
_advisor_lock = asyncio.Lock()


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


async def _tool_list_remote_targets(db: AsyncSession) -> dict:
    winrm = (await db.execute(select(WinRMHostORM))).scalars().all()
    ssh = (await db.execute(select(SSHHostORM))).scalars().all()
    return {
        "winrm_hosts": [
            {"id": h.id, "name": h.custom_name or h.host, "host": h.host, "online": h.is_online}
            for h in winrm
        ],
        "ssh_hosts": [
            {"id": h.id, "name": h.custom_name or h.host, "host": h.host, "online": h.is_online}
            for h in ssh
        ],
        "note": (
            "Configured REMOTE hosts. To recommend upgrading one, put it in set_plan as "
            "type='winrm' or type='ssh' with the host id — that upgrades ALL pending updates "
            "on that host (winget / apt|dnf). Exact pending counts need a live check and are "
            "not shown here, so only recommend a remote upgrade when the user asks or it is "
            "clearly warranted."
        ),
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
        "name": "list_remote_targets",
        "description": (
            "List configured REMOTE hosts (remote Windows over WinRM, and Linux over SSH) "
            "that can be upgraded from here. Use their ids in set_plan with type 'winrm' or "
            "'ssh' to upgrade all pending updates on a host."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_plan",
        "description": (
            "Record the final prioritized, APPLICABLE update plan — the specific updates the "
            "user should apply, most important first. Include ONLY items whose exact `id` "
            "appeared in a tool result: type 'app'/'windows' from list_pending_updates (this "
            "PC), or type 'winrm'/'ssh' from list_remote_targets (a whole remote host — this "
            "upgrades ALL its pending updates). Home Assistant items go in the text only. Call "
            "this once, before the summary; skip it if there is nothing applicable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["app", "windows", "winrm", "ssh"],
                            },
                            "id": {
                                "type": "string",
                                "description": "package_id (app) / update_id (windows) from list_pending_updates, or host id (winrm/ssh) from list_remote_targets",  # noqa: E501
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
    "list_remote_targets": _tool_list_remote_targets,
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

When there are applicable updates, call set_plan once with the top items (most important \
first): local app/Windows updates by their exact ids from list_pending_updates, and/or whole \
remote hosts by id from list_remote_targets (type 'winrm'/'ssh'). Then write your text \
summary. The user can apply the plan with one click.

Reply in the SAME language the user writes in (Arabic or English)."""


async def _run_agent(
    db: AsyncSession,
    client,
    system: str,
    tools: list[dict],
    messages: list[dict[str, Any]],
    capture_plan: bool = False,
) -> dict:
    """Drive the Claude tool-use loop over ``messages`` until a final answer.

    Shared by analyze() and chat(). Returns
    ``{"text", "trace", "model", "truncated", "actions"}``. Raises AdvisorError on
    refusal / empty answer / non-convergence; the caller catches API errors.
    """
    trace: list[dict] = []
    plan: list[dict] = []  # structured applicable actions from the set_plan tool
    deadline = time.monotonic() + _AGENT_DEADLINE  # overall bound across all rounds
    for _ in range(_MAX_ROUNDS):  # cap the agentic loop
        if time.monotonic() > deadline:
            raise AdvisorError("انتهت مهلة المستشار — حاول مجدّدًا / Advisor timed out.")
        resp = await client.messages.create(
            model=settings.advisor_model,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=system,
            tools=tools,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            # Distinguish a real answer from a safety refusal or a truncation.
            if resp.stop_reason == "refusal":
                raise AdvisorError("The model declined this request. Try rephrasing.")
            if not text:
                raise AdvisorError("The model returned an empty answer; please try again.")
            return {
                "text": text,
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
                if capture_plan and block.name == "set_plan":
                    raw = block.input.get("actions", []) if isinstance(block.input, dict) else []
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


async def analyze(db: AsyncSession, lang_hint: str = "en") -> dict:
    """Run the agentic advisor loop and return a prioritized plan + applicable actions."""
    api_key = get_api_key()
    if not api_key:
        raise AdvisorError("AI Advisor is not configured (no Anthropic API key).")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT, max_retries=2)
    ar = lang_hint.startswith("ar")
    user_msg = (
        "Review my home network's update posture and give me a prioritized action plan: "
        "what should I update first, and why? "
        + ("Respond in Arabic." if ar else "Respond in English.")
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    if _advisor_lock.locked():
        raise AdvisorError("المستشار مشغول بطلب آخر — انتظر لحظة / Advisor is busy.")
    async with _advisor_lock:
        try:
            r = await _run_agent(db, client, _SYSTEM, _TOOLS, messages, capture_plan=True)
        except anthropic.APIError as exc:
            logger.error(f"Advisor API error: {exc}")
            raise AdvisorError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
    return {
        "recommendations": r["text"],
        "trace": r["trace"],
        "model": r["model"],
        "truncated": r["truncated"],
        "actions": r["actions"],
    }


# Read-only subset (no set_plan) — chat answers questions, it doesn't build a plan.
_READ_TOOLS = [t for t in _TOOLS if t["name"] != "set_plan"]

_CHAT_SYSTEM = """You are the AI Advisor inside HomeUpdater, a local home-network update app. \
Answer the user's questions about their home network — its devices, known vulnerabilities, and \
pending updates — conversationally and concisely.

Ground every factual answer in the user's ACTUAL local data by using the read-only tools \
(list_devices, check_vulnerabilities, list_pending_updates) — don't guess. If the network hasn't \
been scanned yet (no devices / no data), say so and suggest running a scan. You cannot apply \
updates from chat; if asked to, point the user to the "Analyze my network" plan and its Apply \
button. Reply in the SAME language the user writes in (Arabic or English)."""


async def chat(db: AsyncSession, history: list[dict]) -> dict:
    """Answer a conversational question about the network (read-only tools).

    ``history`` is the client-side ``[{role: 'user'|'assistant', content: str}, ...]``
    with the newest user turn last. Returns ``{reply, trace, model}``.
    """
    api_key = get_api_key()
    if not api_key:
        raise AdvisorError("AI Advisor is not configured (no Anthropic API key).")

    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": str(m["content"])}
        for m in history
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ][
        -20:
    ]  # keep the last ~20 turns
    while messages and messages[0]["role"] != "user":
        messages.pop(0)  # the API requires the conversation to start on a user turn
    if not messages:
        raise AdvisorError("Chat must start with a user message.")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT, max_retries=2)
    if _advisor_lock.locked():
        raise AdvisorError("المستشار مشغول بطلب آخر — انتظر لحظة / Advisor is busy.")
    async with _advisor_lock:
        try:
            r = await _run_agent(
                db, client, _CHAT_SYSTEM, _READ_TOOLS, messages, capture_plan=False
            )
        except anthropic.APIError as exc:
            logger.error(f"Advisor chat API error: {exc}")
            raise AdvisorError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
    return {"reply": r["text"], "trace": r["trace"], "model": r["model"]}


async def apply_plan(db: AsyncSession, actions: list[dict]) -> dict:
    """Apply the advisor's plan — but ONLY updates that are genuinely pending.

    Safety gate: every requested id is validated before anything runs. Local
    app/Windows ids must match a still-pending DB row; remote winrm/ssh ids must
    match a configured host. Unknown ids are skipped, never acted on. A remote
    action upgrades ALL pending updates on that (already-configured) host — the
    same thing the WinRM/Linux pages do.
    """
    from . import software_updates, windows_updates
    from . import ssh as ssh_svc
    from . import winrm_hosts as winrm_svc

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

    # --- remote hosts (WinRM / SSH): validate ids against configured hosts ---
    def _int_ids(kind: str) -> list[int]:
        """Integer host ids for one remote kind. Malformed/non-numeric ids are
        recorded in ``skipped`` (never silently dropped), and we require
        ``isascii()`` because ``str.isdigit()`` accepts Unicode digits such as
        '²' that ``int()`` would then reject with a ValueError."""
        ids: list[int] = []
        for a in actions:
            if a.get("type") != kind:
                continue
            raw = str(a.get("id", "")).strip()
            if raw.isascii() and raw.isdigit():
                ids.append(int(raw))
            elif raw:
                skipped.append(f"{kind}:{raw}")
        return ids

    want_winrm, want_ssh = _int_ids("winrm"), _int_ids("ssh")
    winrm_rows = (
        (await db.execute(select(WinRMHostORM).where(WinRMHostORM.id.in_(want_winrm))))
        .scalars()
        .all()
        if want_winrm
        else []
    )
    ssh_rows = (
        (await db.execute(select(SSHHostORM).where(SSHHostORM.id.in_(want_ssh)))).scalars().all()
        if want_ssh
        else []
    )
    found_winrm = {r.id for r in winrm_rows}
    found_ssh = {r.id for r in ssh_rows}
    skipped += [f"winrm:{i}" for i in want_winrm if i not in found_winrm]
    skipped += [f"ssh:{i}" for i in want_ssh if i not in found_ssh]

    # Remote upgrades run FIRST — while the update slot is still genuinely held
    # by the router's try_claim("install"). The local installers below call
    # update_progress.finish() internally (which clears is_running), so if the
    # possibly-minutes-long remote phase ran after them it would execute with the
    # slot released and could race a concurrent Updates-page install. Each host
    # is guarded so a remote failure is reported, never a 500.
    remote: list[dict] = []
    for row in winrm_rows:
        try:
            r = await winrm_svc.apply_updates(
                row.host,
                row.port,
                row.username,
                row.password,
                row.use_https,
                row.transport,
                row.verify_tls,
            )
            remote.append({"type": "winrm", "host": row.host, "ok": True, "result": r})
        except Exception as exc:
            logger.error(f"Advisor apply (winrm {row.host}) failed: {exc}")
            remote.append({"type": "winrm", "host": row.host, "ok": False, "error": str(exc)})
    for row in ssh_rows:
        try:
            r = await ssh_svc.apply_updates(
                row.host,
                row.port,
                row.username,
                row.password,
                row.pkg_manager,
                row.host_key or None,
            )
            remote.append({"type": "ssh", "host": row.host, "ok": True, "result": r})
        except Exception as exc:
            logger.error(f"Advisor apply (ssh {row.host}) failed: {exc}")
            remote.append({"type": "ssh", "host": row.host, "ok": False, "error": str(exc)})

    # Local installs (winget / WUA) run LAST. Each internally begins+finishes the
    # shared progress slot; running them last means the only post-finish() window
    # is the trailing DB commit — the same negligible one the Updates page has.
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

    # "applied" = plan items that actually SUCCEEDED (local packages + remote hosts).
    applied = (
        (app_res or {}).get("installed", 0)
        + (win_res or {}).get("installed", 0)
        + sum(1 for x in remote if x["ok"])
    )
    return {
        "applied": applied,
        "app": app_res,
        "windows": win_res,
        "remote": remote,
        "skipped": skipped,
    }
