"""record when an update check ran, not when an update was found

Revision ID: e3f6a9c2d5b7
Revises: aca154259cc1
Create Date: 2026-08-09

"آخر فحص" was read off the newest row in ``windows_updates`` — the timestamp of the
last check that FOUND something. A check that found nothing wrote nothing, so it left
no trace at all, and on a tab with no rows the app said "not checked yet" no matter how
many times the user checked. Pressing a button and watching the screen deny that you
pressed it is worse than the missing feature it stands in for.

The two facts are different and now stored separately: this table answers "when did a
check last run, and what did it find", which is knowable even when the answer is zero.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e3f6a9c2d5b7"
down_revision = "aca154259cc1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "update_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.Integer(), nullable=False, server_default="0"),
        # "windows" | "driver" | "software" — one row per surface the user can check.
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        # What the check found. Zero is the case the old design could not express.
        sa.Column("found", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("device_id", "kind", name="uq_update_checks_device_kind"),
    )


def downgrade() -> None:
    op.drop_table("update_checks")
