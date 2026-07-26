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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import AgentCommandORM, AgentORM
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
async def enrol(body: EnrolBody, db: AsyncSession = Depends(get_db)) -> dict:
    """Redeem an enrolment token and create (or re-key) this machine's agent.

    The only agent endpoint not signed by the agent's key — the key is being
    introduced here. It is authenticated by the enrolment token, which is
    single-use, short-lived, and bound to this machine's fingerprint.
    """
    try:
        redeemed = enrolment.redeem(body.token, machine_id=body.machine_id)
    except enrolment.EnrolmentError as exc:
        logger.warning(f"enrolment refused: {exc}")
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


class CheckinBody(BaseModel):
    agent_version: str = Field(default="", max_length=32)
    inventory_count: int = Field(default=0, ge=0, le=100000)
    pending_updates: int = Field(default=0, ge=0, le=100000)


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
@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        (await db.execute(select(AgentORM).order_by(AgentORM.enrolled_at.desc()))).scalars().all()
    )
    return {"agents": [r.to_dict() for r in rows], "total": len(rows)}


@router.post("/{agent_id}/confirm")
async def confirm(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Promote a pending agent to active — the human step an unbound token requires."""
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    if agent.status == "revoked":
        raise HTTPException(status_code=409, detail="agent_revoked")
    agent.status = "active"
    await audit.record_safe(
        db,
        "agent_confirmed",
        actor="user",
        target=agent.name or agent.fingerprint[:12],
        detail={"agent_id": agent.id, "fingerprint": agent.fingerprint},
    )
    return agent.to_dict()


@router.post("/{agent_id}/revoke")
async def revoke(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Stop trusting this agent. Takes effect on its very next request."""
    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown_agent")
    agent.status = "revoked"
    await audit.record_safe(
        db,
        "agent_revoked",
        actor="user",
        target=agent.name or agent.fingerprint[:12],
        detail={"agent_id": agent.id, "fingerprint": agent.fingerprint},
    )
    logger.info(f"agent revoked: {agent.id[:8]}…")
    return agent.to_dict()


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
