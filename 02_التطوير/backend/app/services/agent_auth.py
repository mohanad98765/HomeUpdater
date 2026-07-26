"""Authenticating an agent's request — the only thing standing in front of a fleet.

Every rule here exists because an adversarial review of the protocol design found the
way around its absence (see ``03_الوثائق/AGENT_PROTOCOL.md``):

* **The body cap is enforced before anything else.** Reading a multi-megabyte
  "inventory" and only then discovering the signature is wrong means an unauthenticated
  caller decides how much memory the hub spends. Size first, signature second.
* **The agent id is inside the signed input.** Revocation kills an id, not a key; if
  the id were only an unsigned header, one captured signature would stay valid under a
  freshly enrolled id belonging to the same key.
* **Method and path are inside it too**, so a signature captured on a check-in cannot
  be replayed against the result endpoint.
* **A nonce is stored, not just checked**, and pruned to the signature window — an
  in-memory set is a promise a restart breaks, and an unpruned table is a write target.
* **Clock skew is measured and reported back**, never silently fatal: a machine whose
  clock drifts must be told, not quietly dropped out of the fleet.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request
from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import AgentNonceORM, AgentORM

# A signed request older/newer than this is refused. 120s tolerates ordinary drift
# and NTP correction without giving a captured request a useful lifetime.
SKEW_SECONDS = 120
# Hard ceiling on an agent request body. An inventory of a very large estate is
# still kilobytes; a megabyte means something is wrong or hostile.
MAX_BODY_BYTES = 512 * 1024


class AgentAuthError(HTTPException):
    """401/403 with a machine-readable reason the agent can log and act on."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(status_code=status_code, detail=reason)
        self.reason = reason


def signing_input(agent_id: str, method: str, path: str, timestamp: str, nonce: str, body: bytes):
    """The exact bytes an agent signs. Any change to this breaks every agent — it is
    versioned by the protocol document, not by convenience."""
    digest = hashlib.sha256(body).hexdigest()
    return "\n".join([agent_id, method.upper(), path, timestamp, nonce, digest]).encode("utf-8")


async def read_capped_body(request: Request) -> bytes:
    """Read the body, refusing anything oversized BEFORE it is parsed or verified."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise AgentAuthError(413, "body_too_large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise AgentAuthError(413, "body_too_large")
    return body


async def _check_nonce(db: AsyncSession, agent_id: str, nonce: str) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=SKEW_SECONDS * 2)
    await db.execute(delete(AgentNonceORM).where(AgentNonceORM.seen_at < cutoff))
    seen = await db.get(AgentNonceORM, nonce)
    if seen is not None:
        raise AgentAuthError(401, "replayed_nonce")
    db.add(AgentNonceORM(nonce=nonce, agent_id=agent_id))
    await db.flush()


def _skew_seconds(timestamp: str) -> float:
    try:
        sent = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AgentAuthError(401, "bad_timestamp") from exc
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    return (datetime.now(UTC) - sent).total_seconds()


async def authenticate(request: Request, db: AsyncSession) -> tuple[AgentORM, bytes, float]:
    """Verify a signed agent request. Returns (agent, body, skew_seconds).

    Order matters and is deliberate: size, then headers, then the agent record, then
    the signature, then the nonce. Nothing expensive or persistent happens on behalf
    of a caller who has not yet proved possession of the agent's key.
    """
    body = await read_capped_body(request)

    agent_id = request.headers.get("x-hu-agent", "")
    timestamp = request.headers.get("x-hu-timestamp", "")
    nonce = request.headers.get("x-hu-nonce", "")
    signature_b64 = request.headers.get("x-hu-signature", "")
    if not (agent_id and timestamp and nonce and signature_b64):
        raise AgentAuthError(401, "missing_signature_headers")
    if len(nonce) < 16 or len(nonce) > 64:
        raise AgentAuthError(401, "bad_nonce")

    skew = _skew_seconds(timestamp)
    if abs(skew) > SKEW_SECONDS:
        # Reported, not silent: the response body carries the skew so the agent can
        # log "my clock is 400s off" instead of just "401".
        raise AgentAuthError(401, f"clock_skew:{int(skew)}")

    agent = await db.get(AgentORM, agent_id)
    if agent is None:
        raise AgentAuthError(401, "unknown_agent")
    if agent.status == "revoked":
        raise AgentAuthError(403, "revoked")

    try:
        signature = base64.b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(agent.public_key))
        pub.verify(
            signature,
            signing_input(agent_id, request.method, request.url.path, timestamp, nonce, body),
        )
    except (InvalidSignature, ValueError) as exc:
        logger.warning(f"agent {agent_id[:8]}…: bad signature on {request.url.path}")
        raise AgentAuthError(401, "bad_signature") from exc

    await _check_nonce(db, agent_id, nonce)
    return agent, body, skew
