"""device-scope updates/packages + add the installed_software inventory table

Revision ID: c1d4e7f9a2b3
Revises: 9f2b1a7c4d3e
Create Date: 2026-07-25

Two structural blockers are removed here.

1) FLEET WAS NOT EVEN REPRESENTABLE. ``software_packages.package_id`` and
   ``windows_updates.update_id`` were GLOBALLY unique, so two machines sitting on
   different versions of the same package could not coexist in the schema. Every
   per-device report, console, or evidence pack was blocked behind this. We add
   ``device_id`` and move uniqueness to (device_id, package_id) and
   (device_id, kind, update_id).

   ``device_id = 0`` means THIS PC (the hub), which is the only case that existed
   before, so all legacy rows keep their exact meaning and current queries stay
   correct once they filter on 0. A NOT NULL sentinel is used rather than a
   nullable FK on purpose: NULLs are DISTINCT inside a UNIQUE index, so a
   nullable column would let the hub's own rows duplicate silently.

2) THE APP KNEW WHAT WAS OUTDATED, NEVER WHAT WAS INSTALLED. ``software_packages``
   only holds packages that HAVE an upgrade available. ``installed_software`` adds
   the real inventory (product + version + publisher), which is the prerequisite
   for CPE-accurate CVE matching and for any asset report.

SQLite-safe: ADD COLUMN, DROP/CREATE INDEX and CREATE TABLE are all supported
in place, so no table rebuild is needed. Each step is guarded so the migration is
idempotent on databases that already carry the new shape.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c1d4e7f9a2b3"
down_revision = "9f2b1a7c4d3e"
branch_labels = None
depends_on = None


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}


def _indexes(conn, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall()}


def upgrade() -> None:
    conn = op.get_bind()
    # On the pre-Alembic adoption path (db._run_migrations only STAMPS the
    # baseline) a legacy database can hold `devices` alone. Tables that don't
    # exist yet are skipped here and later created by metadata.create_all with
    # the new shape already in place — so this must never assume they're present.
    present = _tables(conn)

    # --- 1. device_id on both update tables (0 = this PC) --------------------
    for table in ("software_packages", "windows_updates"):
        if table not in present:
            continue
        if "device_id" not in _columns(conn, table):
            op.execute(f"ALTER TABLE {table} ADD COLUMN device_id INTEGER NOT NULL DEFAULT 0")
        idx = _indexes(conn, table)
        if f"ix_{table}_device_id" not in idx:
            op.create_index(f"ix_{table}_device_id", table, ["device_id"], unique=False)

    # --- 2. move uniqueness from global id to (device, id) -------------------
    # The old UNIQUE index is what actually enforced global uniqueness; replace it
    # with a plain lookup index plus a composite UNIQUE one.
    if "software_packages" in present:
        if "ix_software_packages_package_id" in _indexes(conn, "software_packages"):
            op.drop_index("ix_software_packages_package_id", table_name="software_packages")
        if "ix_software_packages_package_id" not in _indexes(conn, "software_packages"):
            op.create_index(
                "ix_software_packages_package_id", "software_packages", ["package_id"], unique=False
            )
        if "uq_software_packages_device_package" not in _indexes(conn, "software_packages"):
            op.create_index(
                "uq_software_packages_device_package",
                "software_packages",
                ["device_id", "package_id"],
                unique=True,
            )

    if "windows_updates" in present:
        if "ix_windows_updates_update_id" in _indexes(conn, "windows_updates"):
            op.drop_index("ix_windows_updates_update_id", table_name="windows_updates")
        if "ix_windows_updates_update_id" not in _indexes(conn, "windows_updates"):
            op.create_index(
                "ix_windows_updates_update_id", "windows_updates", ["update_id"], unique=False
            )
        if "uq_windows_updates_device_kind_update" not in _indexes(conn, "windows_updates"):
            op.create_index(
                "uq_windows_updates_device_kind_update",
                "windows_updates",
                ["device_id", "kind", "update_id"],
                unique=True,
            )

    # --- 3. the installed-software inventory --------------------------------
    if "installed_software" not in present:
        op.create_table(
            "installed_software",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("device_id", sa.Integer(), server_default="0", nullable=False),
            sa.Column("product_id", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("publisher", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("cpe", sa.String(length=255), nullable=False),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_installed_software_device_id", "installed_software", ["device_id"], unique=False
        )
        op.create_index(
            "ix_installed_software_product_id", "installed_software", ["product_id"], unique=False
        )
        op.create_index(
            "uq_installed_software_device_product",
            "installed_software",
            ["device_id", "product_id"],
            unique=True,
        )


def downgrade() -> None:
    # Deliberately one-way. Restoring global uniqueness would have to delete every
    # non-hub row to avoid violating it, i.e. silently destroy fleet data.
    pass
