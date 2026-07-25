"""append-only hash-chained audit_events table

Revision ID: d2e5f8a1b4c6
Revises: c1d4e7f9a2b3
Create Date: 2026-07-25

The evidence pack needs a record an auditor can challenge: "who did what, when,
and can this have been altered since?". A plain table answers the first half only.
Each row here carries a SHA-256 over its own fields plus the previous row's hash,
so removing or editing a single row invalidates every hash after it.

Honest scope: this DETECTS tampering, it does not prevent it — whoever can write
the database file could recompute the chain. What it removes is the ability to
adjust the record *silently*, which is the property that is actually asked about.

``seq`` is UNIQUE so a gap is itself evidence, and there is deliberately no update
or delete path in the application layer.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d2e5f8a1b4c6"
down_revision = "c1d4e7f9a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    present = {
        r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "audit_events" in present:
        return  # idempotent

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        # The exact timestamp string that was hashed — SQLite drops tzinfo on read,
        # so re-deriving it from `at` would make every honest row look tampered.
        sa.Column("at_iso", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # seq UNIQUE: a missing number is itself detectable evidence of a deletion.
    op.create_index("ix_audit_events_seq", "audit_events", ["seq"], unique=True)
    op.create_index("ix_audit_events_at", "audit_events", ["at"], unique=False)
    op.create_index("ix_audit_events_kind", "audit_events", ["kind"], unique=False)
    op.create_index("ix_audit_events_entry_hash", "audit_events", ["entry_hash"], unique=False)


def downgrade() -> None:
    # Dropping the table would destroy the evidence trail it exists to preserve.
    pass
