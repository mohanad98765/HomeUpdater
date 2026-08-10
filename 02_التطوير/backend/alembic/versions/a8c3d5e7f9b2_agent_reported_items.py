"""the hub learns WHICH updates a machine has, not just how many

Revision ID: a8c3d5e7f9b2
Revises: f4a7b2c9e6d1
Create Date: 2026-08-10

The fleet agent could be enrolled securely, could report, and could be commanded — and
every remote install was guaranteed to fail, structurally. The check-in body carried
``inventory_count`` and ``pending_updates``: two integers. The agent refuses any update
id it did not itself report, which is the right rule and the reason a compromised hub
cannot name an update a machine never saw. But the hub was never told the ids, so it
could not name a legitimate one either.

This table is the missing half. A check-in now carries the items themselves and they are
stored per agent, replaced wholesale on each heartbeat, so the hub can offer exactly what
that machine reported and nothing else. The agent's refusal rule is untouched: it still
verifies every id against its own list, so the hub gains the ability to ask without
gaining the ability to dictate.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a8c3d5e7f9b2"
down_revision = "f4a7b2c9e6d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False, index=True),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("current_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("available_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("size_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("requires_reboot", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "kind", "item_id", name="uq_agent_items_agent_kind_item"),
    )
    op.add_column(
        "agents",
        sa.Column("report_truncated", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agents", "report_truncated")
    op.drop_table("agent_items")
