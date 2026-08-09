"""record how many NVD results were actually read, not just how many exist

Revision ID: f4a7b2c9e6d1
Revises: e3f6a9c2d5b7
Create Date: 2026-08-09

The evidence pack printed "Findings (48)" for an estate where NVD had answered 4,494,
and said nothing about a cap. The cause was that the fetch asked NVD for 50 records and
NVD paginates by CVE id, not by severity — so the eight findings shown were the most
severe of the OLDEST fifty. For Chrome that meant reporting 2021 advisories while the
2026 critical ones sat at index 3000, unseen.

The fetch now pages through the whole answer. This column stores how much of it was
read, so the report can state "examined N of M" as a fact rather than leave the reader
to assume it examined everything. A sold audit document that silently covers 1% is worse
than one that says which 1% — that principle is already printed on the pack's own cover.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f4a7b2c9e6d1"
down_revision = "e3f6a9c2d5b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cve_cache",
        sa.Column("examined", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("cve_cache", "examined")
