"""heal devices.mac to nullable (legacy NOT NULL schema)

Revision ID: 9f2b1a7c4d3e
Revises: 2531d17a2b88
Create Date: 2026-07-20

Pre-Alembic builds created ``devices.mac`` as NOT NULL. The MAC-less design
inserts ``mac=NULL`` so several address-less hosts can coexist (SQLite permits
many NULLs in a UNIQUE column). On those legacy tables the insert fails with
``NOT NULL constraint failed: devices.mac`` — and the pre-Alembic adoption path
(db._run_migrations) only *stamps* the baseline, so the old constraint is never
rebuilt away.

SQLite can't drop a NOT NULL in place, and Alembic's ``batch_alter_table``
nullability change proved unreliable here (it left the constraint intact), so we
rebuild the table explicitly: rename → recreate with ``mac`` nullable → copy →
drop old → recreate indexes. Guarded so it's a no-op where ``mac`` is already
nullable (fresh installs, Alembic-managed DBs), which keeps it idempotent and
touches no data there.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "9f2b1a7c4d3e"
down_revision = "2531d17a2b88"
branch_labels = None
depends_on = None

_COLUMNS = (
    "id, mac, ip, hostname, vendor, device_type, "
    "custom_name, notes, first_seen, last_seen, is_online"
)


def _mac_is_not_null(conn) -> bool:
    # PRAGMA table_info rows: (cid, name, type, notnull, dflt_value, pk)
    for col in conn.exec_driver_sql("PRAGMA table_info(devices)").fetchall():
        if col[1] == "mac":
            return bool(col[3])
    return False


def upgrade() -> None:
    conn = op.get_bind()
    if not _mac_is_not_null(conn):
        return  # already nullable — nothing to heal, leave data untouched

    op.execute("ALTER TABLE devices RENAME TO devices__legacy")
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mac", sa.String(length=32), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=False),
        sa.Column("device_type", sa.String(length=32), nullable=False),
        sa.Column("custom_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(f"INSERT INTO devices ({_COLUMNS}) SELECT {_COLUMNS} FROM devices__legacy")
    op.execute("DROP TABLE devices__legacy")  # drops its indexes too, freeing the names
    op.create_index("ix_devices_ip", "devices", ["ip"], unique=False)
    op.create_index("ix_devices_mac", "devices", ["mac"], unique=True)


def downgrade() -> None:
    # Not safely reversible: NULL-mac rows (address-less hosts) would violate a
    # restored NOT NULL. Leave the column nullable.
    pass
