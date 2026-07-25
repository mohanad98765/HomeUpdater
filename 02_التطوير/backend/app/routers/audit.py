"""Audit-trail endpoints: read the chain, verify it, take its digest.

Deliberately READ-ONLY. There is no endpoint to add, edit or delete an entry:
entries are written by the operations they describe, and an API that could edit
them would defeat the reason the chain exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.orm import AuditEventORM
from ..services import audit

router = APIRouter()


@router.get("/events")
async def list_events(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    kind: str = Query(default=""),
) -> dict:
    """Most recent entries first (newest is the most useful by default)."""
    stmt = select(AuditEventORM).order_by(AuditEventORM.seq.desc()).limit(limit)
    if kind:
        stmt = (
            select(AuditEventORM)
            .where(AuditEventORM.kind == kind)
            .order_by(AuditEventORM.seq.desc())
            .limit(limit)
        )
    rows = (await db.execute(stmt)).scalars().all()
    return {"events": [r.to_dict() for r in rows], "returned": len(rows)}


@router.get("/verify")
async def verify_chain(db: AsyncSession = Depends(get_db)) -> dict:
    """Walk the chain and report the first break, if any.

    ``ok: false`` with a ``broken_at`` seq means the record was altered after the
    fact — which is exactly the question an auditor asks about a log.
    """
    return await audit.verify(db)


@router.get("/digest")
async def chain_digest(db: AsyncSession = Depends(get_db)) -> dict:
    """The chain head — one short value that pins the entire history.

    Recorded in the evidence pack so a later replacement of the whole database is
    still detectable: the old head no longer matches.
    """
    return await audit.digest(db)
