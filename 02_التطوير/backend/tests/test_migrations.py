"""
Alembic migration test — runs the real `upgrade head` against a temp database
and asserts the full schema (and the alembic_version stamp) is created.
"""

from __future__ import annotations

import sqlite3

from app.config import settings
from app.db import _run_migrations

EXPECTED_TABLES = {
    "devices",
    "android_devices",
    "software_packages",
    "windows_updates",
    "cve_cache",
    "ha_config",
    "ssh_hosts",
    "alembic_version",
}


def test_upgrade_head_creates_full_schema(tmp_path, monkeypatch):
    db = tmp_path / "migrated.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db.as_posix()}")

    _run_migrations()  # the real startup migration path

    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert EXPECTED_TABLES <= tables

    # devices.mac must be nullable (the schema fix) — column 6 flag `notnull` == 0.
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(devices)")}
    assert cols["mac"][3] == 0, "devices.mac should be nullable"

    version = list(conn.execute("select version_num from alembic_version"))
    assert version, "alembic_version not stamped"
