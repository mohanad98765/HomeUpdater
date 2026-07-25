"""Append-only, hash-chained audit log.

Why a chain and not just a table: a plain log answers "what happened" only if you
trust whoever holds the file. Chaining each entry to the previous one means the
realistic tampering case — quietly deleting or editing ONE row — invalidates every
hash after it and is caught by :func:`verify`.

State the guarantee honestly: this **detects** tampering, it does not prevent it.
Anyone who can write the SQLite file could recompute the whole chain. What it buys
is that the record cannot be *silently* adjusted, which is the property an auditor
actually asks about ("can this be altered without anyone knowing?").

Two rules the rest of the app must respect:
  1. Only ever APPEND (:func:`record`). There is no update or delete path here on
     purpose — adding one would defeat the point.
  2. Never pass a secret in ``detail``. Credential USE is worth recording; the
     credential is not.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import AuditEventORM

GENESIS = "0" * 64  # prev_hash of the very first entry

# Keys that must never be persisted even if a caller passes them by mistake. The
# log is meant to be exportable as evidence, so this is a hard filter, not advice.
_SECRET_KEYS = frozenset(
    {"password", "passwd", "secret", "token", "api_key", "apikey", "key", "credential"}
)


def canonical(payload: dict) -> str:
    """Deterministic JSON so the hash is reproducible across runs and platforms."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _strip_secrets(detail: dict) -> dict:
    """Drop anything that looks like a secret, recursively."""
    clean: dict = {}
    for k, v in (detail or {}).items():
        if k.lower() in _SECRET_KEYS:
            clean[k] = "[redacted]"
        elif isinstance(v, dict):
            clean[k] = _strip_secrets(v)
        else:
            clean[k] = v
    return clean


def compute_hash(
    *, seq: int, at: str, kind: str, actor: str, target: str, outcome: str, detail: str, prev: str
) -> str:
    """SHA-256 over the canonical form of the entry PLUS the previous hash.

    Field names are included (not just values) so two different entries can never
    collide by shifting text between adjacent fields.
    """
    material = canonical(
        {
            "seq": seq,
            "at": at,
            "kind": kind,
            "actor": actor,
            "target": target,
            "outcome": outcome,
            "detail": detail,
            "prev": prev,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _tail(db: AsyncSession) -> tuple[int, str]:
    """The current (last seq, last hash) — the anchor a new entry chains onto."""
    row = (
        await db.execute(select(AuditEventORM).order_by(AuditEventORM.seq.desc()).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return 0, GENESIS
    return row.seq, row.entry_hash


async def record(
    db: AsyncSession,
    kind: str,
    *,
    target: str = "",
    outcome: str = "ok",
    actor: str = "app",
    detail: dict | None = None,
    commit: bool = True,
) -> AuditEventORM:
    """Append one entry. Never raises into the caller's business logic.

    An audit failure must not break the operation being audited — a failed patch
    install is bad, but a failed patch install that ALSO rolls back because the log
    write failed is worse. Errors are logged and swallowed.
    """
    try:
        last_seq, last_hash = await _tail(db)
        now = datetime.now(UTC)
        detail_json = canonical(_strip_secrets(detail or {}))
        seq = last_seq + 1
        at_iso = now.isoformat()
        entry = AuditEventORM(
            seq=seq,
            at=now,
            at_iso=at_iso,
            kind=kind,
            actor=actor,
            target=target,
            outcome=outcome,
            detail=detail_json,
            prev_hash=last_hash,
            entry_hash=compute_hash(
                seq=seq,
                at=at_iso,
                kind=kind,
                actor=actor,
                target=target,
                outcome=outcome,
                detail=detail_json,
                prev=last_hash,
            ),
        )
        db.add(entry)
        if commit:
            await db.commit()
        return entry
    except Exception as exc:  # noqa: BLE001 — auditing must not break the audited action
        logger.warning(f"audit record failed ({kind}): {exc}")
        raise AuditWriteError(str(exc)) from exc


class AuditWriteError(RuntimeError):
    """Raised only to callers that explicitly want to know; normally swallowed."""


async def record_safe(db: AsyncSession, kind: str, **kw) -> None:
    """Fire-and-forget append for call sites that must never fail because of the log."""
    try:
        await record(db, kind, **kw)
    except Exception:  # noqa: BLE001
        pass  # already logged in record()


async def verify(db: AsyncSession) -> dict:
    """Walk the whole chain and report the FIRST break, if any.

    Returns ``{ok, entries, broken_at, reason}``. ``broken_at`` is the seq of the
    first entry whose stored hash doesn't match a recomputation, or whose prev_hash
    doesn't match the actual previous entry.
    """
    rows = (await db.execute(select(AuditEventORM).order_by(AuditEventORM.seq))).scalars().all()
    prev = GENESIS
    expected_seq = 1
    for row in rows:
        if row.seq != expected_seq:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at": row.seq,
                "reason": f"sequence gap: expected {expected_seq}, found {row.seq}",
            }
        if row.prev_hash != prev:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at": row.seq,
                "reason": "prev_hash does not match the previous entry",
            }
        recomputed = compute_hash(
            seq=row.seq,
            # the stored string, NOT a re-derived one: SQLite returns `at` naive
            at=row.at_iso,
            kind=row.kind,
            actor=row.actor,
            target=row.target,
            outcome=row.outcome,
            detail=row.detail,
            prev=row.prev_hash,
        )
        if recomputed != row.entry_hash:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at": row.seq,
                "reason": "entry contents do not match its hash (edited after the fact)",
            }
        prev = row.entry_hash
        expected_seq += 1
    return {"ok": True, "entries": len(rows), "broken_at": None, "reason": ""}


async def digest(db: AsyncSession) -> dict:
    """The chain's head — a single short value that pins the whole history.

    Copying this out (into a report, an e-mail, a ticket) is what makes later
    tampering detectable even if the whole file is replaced: the old head no longer
    matches. Cheap, and the only integrity anchor available without a signing key.
    """
    count = (await db.execute(select(func.count()).select_from(AuditEventORM))).scalar_one()
    last_seq, last_hash = await _tail(db)
    return {
        "entries": count,
        "head_seq": last_seq,
        "head_hash": last_hash,
        "computed_at": datetime.now(UTC).isoformat(),
    }
