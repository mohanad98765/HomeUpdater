"""Agent endpoints — enrolment, signed check-in, results, and the operator's view.

Two audiences, two authentication models, deliberately separated:

* ``/api/agents/enrol|checkin|result`` are called BY an agent from another machine.
  They are not covered by the hub's session-token or login gates — those gates exist
  to stop a local process driving the elevated UI API, and an agent has neither the
  launch token nor a browser session. They are not "exempt" either: every one of them
  authenticates with something stronger (an enrolment token, then an Ed25519 signature
  over the request) and refuses anything it cannot verify.
* the rest are the operator's, behind the hub's normal gates.

An agent can only ever be TOLD things it asked for: there is no inbound connection to
the target, and commands ride back on the response to a check-in the agent initiated.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import AgentCommandORM, AgentItemORM, AgentNonceORM, AgentORM
from ..services import agent_auth, audit, enrolment

router = APIRouter()

# The complete set of things an agent will do. Adding one is a protocol decision,
# not a configuration change — and there is no "run this string" member by design.
COMMAND_KINDS = {
    "inventory": (),
    "windows_updates_check": (),
    "windows_updates_install": ("update_ids",),
    "software_upgrade": ("product_ids",),
}
MAX_IDS_PER_COMMAND = 200


class EnrolBody(BaseModel):
    token: str = Field(min_length=8, max_length=4096)
    machine_id: str = Field(min_length=1, max_length=256)
    public_key: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    name: str = Field(default="", max_length=120)
    os_name: str = Field(default="", max_length=120)
    agent_version: str = Field(default="", max_length=32)


class CommandBody(BaseModel):
    kind: str = Field(max_length=32)
    update_ids: list[str] | None = Field(default=None, max_length=MAX_IDS_PER_COMMAND)
    product_ids: list[str] | None = Field(default=None, max_length=MAX_IDS_PER_COMMAND)


# ---------------------------------------------------------------- agent-facing
@router.post("/enrol")
async def enrol(body: EnrolBody, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Redeem an enrolment token and create (or re-key) this machine's agent.

    The only agent endpoint not signed by the agent's key — the key is being
    introduced here. It is authenticated by the enrolment token, which is
    single-use, short-lived, and bound to this machine's fingerprint.
    """
    try:
        redeemed = enrolment.redeem(body.token, machine_id=body.machine_id)
    except enrolment.EnrolmentError as exc:
        logger.warning(f"enrolment refused: {exc}")
        agent_auth.note_refusal(
            f"enrol:{exc}", path="/api/agents/enrol", source=agent_auth._client_ip(request)
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    fingerprint = redeemed["agent_fingerprint"]
    bound = bool(redeemed.get("bound"))
    existing = (
        await db.execute(select(AgentORM).where(AgentORM.fingerprint == fingerprint))
    ).scalar_one_or_none()

    if existing is not None:
        # Re-enrolment of a known machine (agent reinstalled, key rotated). Keep the
        # id so its history stays attached, and never resurrect a revoked agent
        # silently — an operator revoked it for a reason.
        if existing.status == "revoked":
            agent_auth.note_refusal(
                "agent_revoked",
                agent_id=existing.id,
                path="/api/agents/enrol",
                source=agent_auth._client_ip(request),
            )
            raise HTTPException(status_code=403, detail="agent_revoked")
        existing.public_key = body.public_key
        existing.name = body.name or existing.name
        existing.os_name = body.os_name or existing.os_name
        existing.agent_version = body.agent_version or existing.agent_version
        existing.status = "active" if bound else "pending"
        agent = existing
    else:
        agent = AgentORM(
            id=str(uuid.uuid4()),
            fingerprint=fingerprint,
            public_key=body.public_key,
            name=body.name,
            os_name=body.os_name,
            agent_version=body.agent_version,
            # An unbound token could have been redeemed by ANY machine, so the agent
            # it produces waits for a human to confirm the fingerprint on the target.
            status="active" if bound else "pending",
        )
        db.add(agent)
    await db.flush()
    # Persist the request's own effect BEFORE the audit append. get_db() never
    # commits, so this used to ride on audit.record's commit — and record_safe
    # swallows every failure, so a failed audit write discarded the whole
    # transaction while the request still returned 200. Measured: a byte-identical
    # signed request replayed successfully because its nonce row went with it.
    await db.commit()
    await audit.record_safe(
        db,
        "agent_enrol",
        actor="agent",
        target=agent.name or fingerprint[:12],
        detail={"agent_id": agent.id, "fingerprint": fingerprint, "bound": bound},
    )
    logger.info(f"agent enrolled: {agent.id[:8]}… status={agent.status} bound={bound}")
    return {
        "agent_id": agent.id,
        "status": agent.status,
        "hub_public_key": redeemed["hub_public_key"],
        # Said plainly so the agent can show it: an unbound enrolment is not trusted
        # until the operator confirms this fingerprint in the hub.
        "requires_confirmation": agent.status == "pending",
        "fingerprint": fingerprint,
    }


# What one check-in may carry. The signed-body cap is 600 KB, and 200 updates plus 300
# packages is roughly 90 KB — comfortable, while still bounding what a signed agent can
# make the hub store. An agent with more says so (report_truncated) instead of quietly
# sending a partial list.
MAX_REPORTED_UPDATES = 200
MAX_REPORTED_PACKAGES = 300


class ReportedUpdate(BaseModel):
    """A pending update as the agent's own machine sees it."""

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=300)
    kind: str = Field(default="windows", pattern=r"^(windows|driver)$")
    severity: str = Field(default="", max_length=32)
    size_mb: float = Field(default=0.0, ge=0, le=1_000_000)
    requires_reboot: bool = False


class ReportedPackage(BaseModel):
    """An upgradable application on the agent's machine."""

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=300)
    current_version: str = Field(default="", max_length=64)
    available_version: str = Field(default="", max_length=64)


class CheckinBody(BaseModel):
    agent_version: str = Field(default="", max_length=32)
    inventory_count: int = Field(default=0, ge=0, le=100000)
    pending_updates: int = Field(default=0, ge=0, le=100000)
    # The lists are what make a remote install possible: the agent refuses any id it did
    # not itself report, so until the hub was told the ids it could not name a
    # legitimate one either, and every remote install failed by construction.
    updates: list[ReportedUpdate] = Field(default_factory=list, max_length=MAX_REPORTED_UPDATES)
    packages: list[ReportedPackage] = Field(default_factory=list, max_length=MAX_REPORTED_PACKAGES)
    truncated: bool = False


async def _store_reported_items(db: AsyncSession, agent_id: str, payload: CheckinBody) -> None:
    """Replace this agent's reported items wholesale.

    A check-in is a snapshot, not a delta. Merging would leave ghosts: an update
    installed by Windows itself, or by someone sitting at that machine, would stay on
    the hub's list and the operator would try to install it again — and the agent would
    refuse, correctly, leaving a failure nobody could explain.
    """
    now = datetime.now(UTC)
    await db.execute(delete(AgentItemORM).where(AgentItemORM.agent_id == agent_id))
    for upd in payload.updates:
        db.add(
            AgentItemORM(
                agent_id=agent_id,
                kind=upd.kind,
                item_id=upd.id,
                title=upd.title,
                severity=upd.severity,
                size_mb=upd.size_mb,
                requires_reboot=upd.requires_reboot,
                reported_at=now,
            )
        )
    for pkg in payload.packages:
        db.add(
            AgentItemORM(
                agent_id=agent_id,
                kind="package",
                item_id=pkg.id,
                title=pkg.name,
                current_version=pkg.current_version,
                available_version=pkg.available_version,
                reported_at=now,
            )
        )


@router.post("/checkin")
async def checkin(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Signed heartbeat. Returns the commands queued for this agent, and nothing else.

    A ``pending`` agent gets an empty queue: it is enrolled but not yet confirmed, and
    handing it work would make the confirmation step decorative.
    """
    agent, body, skew = await agent_auth.authenticate(request, db)
    try:
        payload = CheckinBody.model_validate_json(body or b"{}")
    except Exception as exc:  # noqa: BLE001 — a malformed body from a signed agent
        raise HTTPException(status_code=422, detail="bad_checkin_body") from exc

    agent.last_seen = datetime.now(UTC)
    agent.last_skew_seconds = round(skew, 1)
    agent.agent_version = payload.agent_version or agent.agent_version
    agent.inventory_count = payload.inventory_count
    agent.pending_updates = payload.pending_updates
    agent.report_truncated = bool(payload.truncated)
    await _store_reported_items(db, agent.id, payload)

    commands: list[dict] = []
    if agent.status == "active":
        rows = (
            (
                await db.execute(
                    select(AgentCommandORM)
                    .where(
                        AgentCommandORM.agent_id == agent.id,
                        AgentCommandORM.status == "queued",
                    )
                    .order_by(AgentCommandORM.id)
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC)
        for row in rows:
            row.status = "sent"
            row.sent_at = now
            commands.append({"id": row.id, "kind": row.kind, **json.loads(row.payload or "{}")})

    # The check-in itself is audited as a SUMMARY. Writing a full inventory into the
    # hash-chained log on every heartbeat would bloat a structure that verify() reads
    # end to end — the log records that a machine reported, not what it contains.
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_checkin",
        actor="agent",
        target=agent.name or agent.fingerprint[:12],
        detail={
            "agent_id": agent.id,
            "inventory": payload.inventory_count,
            "pending_updates": payload.pending_updates,
            "commands": len(commands),
        },
    )
    return {
        "status": agent.status,
        "commands": commands,
        # Told, not silently tolerated: an agent whose clock drifts toward the window
        # edge can fix itself before it stops being able to talk to the hub at all.
        "clock_skew_seconds": round(skew, 1),
        "max_skew_seconds": agent_auth.SKEW_SECONDS,
    }


class ResultBody(BaseModel):
    command_id: int
    ok: bool
    summary: str = Field(default="", max_length=2000)
    reboot_required: bool = False


@router.post("/result")
async def result(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Signed command outcome. An agent may only close its OWN commands."""
    agent, body, _skew = await agent_auth.authenticate(request, db)
    try:
        payload = ResultBody.model_validate_json(body or b"{}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="bad_result_body") from exc

    command = await db.get(AgentCommandORM, payload.command_id)
    # Confused-deputy check: without it, any agent could close (or fake the outcome
    # of) a command issued to a different machine.
    if command is None or command.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="command_not_found")

    command.status = "done" if payload.ok else "failed"
    command.completed_at = datetime.now(UTC)
    command.result = payload.summary[:2000]
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_command_result",
        actor="agent",
        target=agent.name or agent.fingerprint[:12],
        outcome="ok" if payload.ok else "failed",
        detail={
            "agent_id": agent.id,
            "command_id": command.id,
            "kind": command.kind,
            "reboot_required": payload.reboot_required,
        },
    )
    return {"accepted": True}


# ------------------------------------------------------------- operator-facing
@router.get("/listener")
async def listener_status() -> dict:
    """Where agents should point, and what fingerprint they will pin.

    Deliberately an operator route (behind the hub's gates) and NOT on the agent
    listener's allowlist: the socket that faces the network must not describe the
    hub's configuration to anyone who connects to it.
    """
    from ..agent_listener import listener

    return listener.status()


class RegenerateBody(BaseModel):
    acknowledge_agents: int = Field(ge=0)


@router.post("/listener/certificate/regenerate")
async def regenerate_certificate(body: RegenerateBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Issue a NEW hub certificate. Every enrolled agent pinned the old one, so this
    breaks them until they re-enrol — said here rather than discovered in the field.

    ``acknowledge_agents`` must equal how many agents this will break. It is not a
    confirmation checkbox: a mismatch means the caller's screen was stale about the
    very number that measures the damage, so the answer is to go and re-read it.
    """
    from ..agent_listener import listener
    from ..services import agent_tls

    breakable = (
        (await db.execute(select(AgentORM).where(AgentORM.status != "revoked"))).scalars().all()
    )
    if body.acknowledge_agents != len(breakable):
        raise HTTPException(status_code=409, detail=f"agent_count_mismatch:{len(breakable)}")

    details = agent_tls.ensure_cert(force=True)
    if listener.running:
        listener.stop()
        listener.start()
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_tls_regenerated",
        actor="user",
        target="agent-listener",
        detail={"fingerprint": details["fingerprint_sha256"]},
    )
    return {
        **details,
        "warning": "every enrolled agent pinned the previous certificate and must re-enrol",
        "broken_agents": [
            {"id": a.id, "name": a.name, "fingerprint_head": a.fingerprint[:8]} for a in breakable
        ],
    }


class EnrolmentTokenBody(BaseModel):
    """What the operator is asking for, stated rather than inferred.

    ``machine_fingerprint`` is what ``HomeUpdater.exe --agent --show-id`` prints on the
    target; supplying it binds the token to that machine and the agent arrives ACTIVE.
    Without it the token is redeemable by anything on the network for 15 minutes, so
    ``allow_any_machine`` must be sent explicitly — an unbound credential is a decision.
    """

    target_hint: str = Field(default="", max_length=80)
    machine_fingerprint: str = Field(default="", max_length=64)
    allow_any_machine: bool = False


@router.post("/enrolment-token")
async def create_enrolment_token(
    body: EnrolmentTokenBody, db: AsyncSession = Depends(get_db)
) -> dict:
    """Mint one single-use enrolment token. Shown once; there is no GET counterpart."""
    fp = body.machine_fingerprint.replace(" ", "").replace("-", "").lower()
    if fp and body.allow_any_machine:
        # Both would mean the caller does not know what it wants; picking one silently
        # is how a token ends up unbound while the operator believes it is bound.
        raise HTTPException(status_code=400, detail="fingerprint_and_allow_any_machine")
    if not fp and not body.allow_any_machine:
        raise HTTPException(status_code=400, detail="unbound_requires_optin")
    try:
        minted = enrolment.mint(
            target_hint=body.target_hint,
            machine_fingerprint=fp or None,
            allow_any_machine=body.allow_any_machine,
        )
    except enrolment.EnrolmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_enrolment_token_minted",
        actor="user",
        target=body.target_hint or "(unnamed)",
        # Never the token and never the nonce: the audit log is exported inside the
        # paid Evidence Pack, so a live credential must not travel in it.
        detail={"bound": bool(fp), "target_fp_head": fp[:8], "expires_at": minted.expires_at},
    )
    logger.info(f"enrolment token minted (bound={bool(fp)})")
    return {
        "token": minted.token,
        "expires_at": minted.expires_at,
        "bound": bool(fp),
        "requires_confirmation": not fp,
        "target_hint": body.target_hint,
    }


class ListenerBody(BaseModel):
    enabled: bool


@router.post("/listener")
async def set_listener(body: ListenerBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Turn the agent port on or off, live, and persist the choice.

    A dedicated route rather than a field on the generic settings endpoint: that one
    has no start/stop hook, so the persisted flag and the live socket would disagree —
    which is exactly the state this feature shipped in before this endpoint existed.
    """
    import time

    from ..agent_listener import listener
    from ..config import save_settings

    save_settings({"agent_listener_enabled": body.enabled})
    if body.enabled:
        listener.start()
        # start() hands off to a thread, so `running` is False for a moment. Returning
        # immediately would report "off" after every successful enable.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not (listener.running or listener.error):
            time.sleep(0.1)
    else:
        listener.stop()
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_listener_toggled",
        actor="user",
        target="agent-listener",
        detail={"enabled": body.enabled, "running": listener.running},
    )
    # A failed start is not a client error — a port in use is a fact about the machine.
    # It comes back as status with `error` populated, and the UI names the cause.
    return listener.status()


@router.get("/refusals")
async def refusals(limit: int = 20, db: AsyncSession = Depends(get_db)) -> dict:
    """Why a machine went quiet — every request the agent port refused.

    In memory, cleared on restart, capped. Agent names are resolved here so the UI
    does not have to join, and an id with no matching row stays null rather than
    inventing a name for a machine that was forgotten.
    """
    entries = agent_auth.recent_refusals(max(1, min(limit, 100)))
    ids = {e["agent_id"] for e in entries if e["agent_id"]}
    names: dict[str, str] = {}
    if ids:
        rows = (await db.execute(select(AgentORM).where(AgentORM.id.in_(ids)))).scalars().all()
        names = {r.id: r.name or r.fingerprint[:12] for r in rows}
    return {
        "refusals": [{**e, "agent_name": names.get(e["agent_id"])} for e in entries],
        "total": len(entries),
    }


def _for_operator(agent: AgentORM) -> dict:
    """One agent as the operator's screen may see it.

    A PENDING agent's fingerprint is MASKED past the first group. The confirm step
    asks the operator to type the last eight characters, and those exist only on the
    target machine's screen - rendering them one input away would turn the check into
    a transcription exercise and back into the one-click promote it replaced.
    Confirmed and revoked agents show the whole thing: there is nothing left to prove.
    """
    data = agent.to_dict()
    fp = agent.fingerprint
    data["fingerprint_head"] = fp[:8]
    if agent.status == "pending":
        data["fingerprint"] = None
        data["fingerprint_masked"] = f"{fp[:8]} •••••••• •••••••• ••••••••"
    return data


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        (await db.execute(select(AgentORM).order_by(AgentORM.enrolled_at.desc()))).scalars().all()
    )
    counts = {"pending": 0, "active": 0, "revoked": 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "agents": [_for_operator(r) for r in rows],
        "total": len(rows),
        "counts": counts,
    }


class ConfirmBody(BaseModel):
    fingerprint_suffix: str = Field(min_length=1, max_length=32)


# Wrong suffixes per agent id, so a mistyped confirmation cannot become a guessing
# loop against the 8 hex characters that stand between a stranger's machine and trust.
_CONFIRM_ATTEMPTS: dict[str, list[datetime]] = {}
_CONFIRM_WINDOW_SECONDS = 900
_CONFIRM_MAX_ATTEMPTS = 5


@router.post("/{agent_id}/confirm")
async def confirm(agent_id: str, body: ConfirmBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Promote a pending agent to active — the human step an unbound token requires.

    The operator must type the LAST eight characters of the fingerprint. An unbound
    token is redeemable by any machine on the network, so a stranger's agent can land
    in this list beside the intended one; a button alone would promote whichever the
    operator clicked. Those eight characters are printed on the target's own screen
    (``--agent --show-id``, or the enrolment line), so answering the challenge is a
    proof of access to the machine being trusted.
    """
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    if agent.status == "revoked":
        raise HTTPException(status_code=409, detail="agent_revoked")
    if agent.status == "active":
        # Previously a silent no-op, which reads as "confirmed!" for an agent someone
        # else may have confirmed a moment ago.
        raise HTTPException(status_code=409, detail="agent_already_active")

    now = datetime.now(UTC)
    tries = [
        t
        for t in _CONFIRM_ATTEMPTS.get(agent_id, [])
        if (now - t).total_seconds() < _CONFIRM_WINDOW_SECONDS
    ]
    if len(tries) >= _CONFIRM_MAX_ATTEMPTS:
        _CONFIRM_ATTEMPTS[agent_id] = tries
        raise HTTPException(status_code=429, detail="too_many_attempts")

    given = body.fingerprint_suffix.replace(" ", "").replace("-", "").lower()
    if given != agent.fingerprint[-8:]:
        tries.append(now)
        _CONFIRM_ATTEMPTS[agent_id] = tries
        await db.commit()  # durable before the audit append — see above
        await audit.record_safe(
            db,
            "agent_confirm_refused",
            actor="user",
            outcome="failed",
            target=agent.name or agent.fingerprint[:12],
            # The correct value is not echoed anywhere, including here.
            detail={"agent_id": agent.id, "fingerprint_head": agent.fingerprint[:8]},
        )
        raise HTTPException(status_code=400, detail="fingerprint_mismatch")

    _CONFIRM_ATTEMPTS.pop(agent_id, None)
    agent.status = "active"
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_confirmed",
        actor="user",
        target=agent.name or agent.fingerprint[:12],
        detail={"agent_id": agent.id, "fingerprint": agent.fingerprint},
    )
    return _for_operator(agent)


@router.post("/{agent_id}/revoke")
async def revoke(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Stop trusting this agent. Takes effect on its very next request."""
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    agent.status = "revoked"
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_revoked",
        actor="user",
        target=agent.name or agent.fingerprint[:12],
        detail={"agent_id": agent.id, "fingerprint": agent.fingerprint},
    )
    logger.info(f"agent revoked: {agent.id[:8]}…")
    return _for_operator(agent)


@router.delete("/{agent_id}")
async def forget(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Remove a REVOKED agent so that machine can enrol again.

    Revocation is otherwise a one-way door: ``enrol`` refuses a known revoked
    fingerprint forever, so one mis-click permanently bars a machine with no way back.
    Gated on ``revoked`` so it can never become a shortcut around revoking, and the
    audit trail stays — the rows leave the list, not the history.
    """
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    if agent.status != "revoked":
        raise HTTPException(status_code=409, detail="agent_not_revoked")
    await db.execute(delete(AgentCommandORM).where(AgentCommandORM.agent_id == agent_id))
    await db.execute(delete(AgentNonceORM).where(AgentNonceORM.agent_id == agent_id))
    fingerprint, name = agent.fingerprint, agent.name
    await db.delete(agent)
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_forgotten",
        actor="user",
        target=name or fingerprint[:12],
        detail={"agent_id": agent_id, "fingerprint": fingerprint},
    )
    logger.info(f"agent forgotten: {agent_id[:8]}…")
    return {"deleted": True, "agent_id": agent_id}


@router.post("/{agent_id}/command")
async def queue_command(
    agent_id: str, body: CommandBody, db: AsyncSession = Depends(get_db)
) -> dict:
    """Queue one enumerated command. Unknown kinds and missing fields are refused."""
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    if agent.status != "active":
        raise HTTPException(status_code=409, detail=f"agent_{agent.status}")
    if body.kind not in COMMAND_KINDS:
        raise HTTPException(status_code=400, detail="unknown_command_kind")

    required = COMMAND_KINDS[body.kind]
    payload: dict[str, list[str]] = {}
    for field in required:
        values = getattr(body, field) or []
        if not values:
            raise HTTPException(status_code=400, detail=f"{field}_required")
        payload[field] = [str(v)[:200] for v in values][:MAX_IDS_PER_COMMAND]
    # Fields that do not belong to this kind are dropped rather than stored: a payload
    # the agent will not read has no business sitting in the queue.
    command = AgentCommandORM(
        agent_id=agent.id, kind=body.kind, payload=json.dumps(payload, ensure_ascii=False)
    )
    db.add(command)
    await db.flush()
    await db.commit()  # durable before the audit append — see above
    await audit.record_safe(
        db,
        "agent_command_issued",
        actor="user",
        target=agent.name or agent.fingerprint[:12],
        detail={
            "agent_id": agent.id,
            "command_id": command.id,
            "kind": command.kind,
            "count": sum(len(v) for v in payload.values()),
        },
    )
    return command.to_dict()


@router.get("/{agent_id}/items")
async def list_reported_items(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """What this machine last reported it has.

    The operator can only ever act on this list, and the agent independently refuses
    anything outside its own — so the hub can ask, and cannot dictate.
    """
    agent = (await db.execute(select(AgentORM).where(AgentORM.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent_not_found")

    rows = (
        (
            await db.execute(
                select(AgentItemORM)
                .where(AgentItemORM.agent_id == agent_id)
                .order_by(AgentItemORM.kind, AgentItemORM.title)
            )
        )
        .scalars()
        .all()
    )
    return {
        "agent_id": agent_id,
        "status": agent.status,
        "updates": [r.to_dict() for r in rows if r.kind in ("windows", "driver")],
        "packages": [r.to_dict() for r in rows if r.kind == "package"],
        "reported_at": rows[0].reported_at.isoformat() if rows else None,
        # Said, not implied: a machine with more items than one body carries would
        # otherwise present a partial list as its whole state.
        "truncated": agent.report_truncated,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
    }


@router.get("/{agent_id}/commands")
async def list_commands(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        (
            await db.execute(
                select(AgentCommandORM)
                .where(AgentCommandORM.agent_id == agent_id)
                .order_by(AgentCommandORM.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {"commands": [r.to_dict() for r in rows]}
