"""Regression: a pre-Alembic DB with ``devices.mac NOT NULL`` must be healed to
nullable on startup, WITHOUT losing device rows — otherwise every scan that finds
a MAC-less host (e.g. the local machine) dies with
``NOT NULL constraint failed: devices.mac``.

Drives the real app path (db._run_migrations) against a throwaway temp DB, with
settings.database_url monkeypatched so it never touches the user's real database.
"""

from __future__ import annotations

import sqlite3

from app import db as dbmod
from app.config import settings

_LEGACY_DDL = """
CREATE TABLE devices (
  id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  mac VARCHAR(32) NOT NULL,
  ip VARCHAR(45) NOT NULL,
  hostname VARCHAR(255) NOT NULL,
  vendor VARCHAR(255) NOT NULL,
  device_type VARCHAR(32) NOT NULL,
  custom_name VARCHAR(255) NOT NULL,
  notes TEXT NOT NULL,
  first_seen DATETIME NOT NULL,
  last_seen DATETIME NOT NULL,
  is_online BOOLEAN NOT NULL
);
CREATE UNIQUE INDEX ix_devices_mac ON devices (mac);
CREATE INDEX ix_devices_ip ON devices (ip);
"""

_COLS = "mac,ip,hostname,vendor,device_type,custom_name,notes,first_seen,last_seen,is_online"
_TS = "2026-01-01 00:00:00"


def _insert(con, mac, ip, hostname="h", custom_name="", notes=""):
    con.execute(
        f"INSERT INTO devices ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mac, ip, hostname, "", "unknown", custom_name, notes, _TS, _TS, 1),
    )


def _mac_notnull(con) -> int:
    return next(c[3] for c in con.execute("PRAGMA table_info(devices)").fetchall() if c[1] == "mac")


def test_legacy_not_null_mac_db_is_healed_and_data_kept(tmp_path, monkeypatch):
    dbfile = tmp_path / "homeupdater.db"
    con = sqlite3.connect(dbfile)
    con.executescript(_LEGACY_DDL)
    _insert(con, "AA:BB:CC:DD:EE:FF", "192.168.3.1", "router", "بيتنا", "ملاحظة")
    con.commit()
    con.close()

    # Point BOTH _run_migrations and alembic env.py at the temp DB (env.py reads
    # settings.database_url live), so the real appdata DB is never touched.
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{dbfile}")
    dbmod._run_migrations()  # legacy adoption -> stamp baseline -> upgrade (runs the heal)

    con = sqlite3.connect(dbfile)
    try:
        assert _mac_notnull(con) == 0  # mac is nullable now
        assert con.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1  # row preserved
        preserved = con.execute("SELECT custom_name, notes FROM devices").fetchone()
        assert preserved == ("بيتنا", "ملاحظة")  # user data intact
        # The unique index survived (multiple NULLs are allowed under it in SQLite).
        idx = [x[1] for x in con.execute("PRAGMA index_list(devices)").fetchall()]
        assert "ix_devices_mac" in idx
        # The failing insert now succeeds — and two MAC-less hosts coexist.
        _insert(con, None, "192.168.3.72", "mouni")
        _insert(con, None, "192.168.3.99", "phone")
        con.commit()
        assert con.execute("SELECT COUNT(*) FROM devices WHERE mac IS NULL").fetchone()[0] == 2
    finally:
        con.close()


def test_heal_is_idempotent_noop_on_already_nullable(tmp_path, monkeypatch):
    # A DB that's already nullable must pass through untouched (fresh installs).
    dbfile = tmp_path / "homeupdater.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{dbfile}")
    dbmod._run_migrations()  # fresh DB -> full upgrade, mac created nullable
    con = sqlite3.connect(dbfile)
    try:
        assert _mac_notnull(con) == 0
        _insert(con, None, "10.0.0.5", "x")  # NULL insert works out of the box
        con.commit()
    finally:
        con.close()
