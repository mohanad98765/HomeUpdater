"""stop asserting what cannot be proved: applied_by_us, applicable

Revision ID: b6d9e1f4c8a3
Revises: a8c3d5e7f9b2
Create Date: 2026-08-10

Two columns, one principle. An adversarial audit reproduced both defects by driving the
real handlers, and both made the SOLD report overstate itself:

* An update that stops appearing in the Windows Update search was recorded as installed
  with result code 2 ("Succeeded") and printed in the pack under "Applied updates".
  Windows also withdraws an update when it is superseded, expired, declined or hidden —
  and Defender definitions are superseded several times a day. Proven: a January
  cumulative update nobody installed appeared in the hash-stamped report as applied.
  ``applied_by_us`` is written only by the install path.

* Findings were capped at the eight most severe per product while the same page printed
  "NVD records examined: N / N" beside them, which reads as "these are all of them".
  ``applicable`` records how many advisories actually applied before the cap.

Existing rows default to FALSE and 0 deliberately. We cannot tell retroactively which
updates this app installed, and a report that guesses is the thing being fixed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b6d9e1f4c8a3"
down_revision = "a8c3d5e7f9b2"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    """A legacy database may predate a table entirely — the repair path in
    ``test_devices_mac_migration`` builds exactly such a database. A migration that
    assumes every table exists turns an upgrade into a dead end for the oldest installs,
    which are the ones least able to recover.
    """
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has("windows_updates"):
        op.add_column(
            "windows_updates",
            sa.Column("applied_by_us", sa.Boolean(), nullable=False, server_default="0"),
        )
    if _has("cve_cache"):
        op.add_column(
            "cve_cache",
            sa.Column("applicable", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _has("cve_cache"):
        op.drop_column("cve_cache", "applicable")
    if _has("windows_updates"):
        op.drop_column("windows_updates", "applied_by_us")
