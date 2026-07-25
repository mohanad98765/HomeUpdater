"""The hash-chained audit log — the integrity claim, actually exercised.

A chain is only worth shipping if tampering really is detected, so these tests
edit, delete and reorder rows behind the service's back and assert verification
catches each case. They also pin the two properties that make the log safe to
export as evidence: secrets are never written, and an audit failure never breaks
the operation being audited.

Chain-internals tests use their OWN engine/session per step on purpose: a single
shared ORM session would serve cached objects after raw-SQL tampering and hide the
very thing being proven.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.orm import AuditEventORM, Base
from app.services import audit

CSRF = {"X-HomeUpdater": "1"}


@pytest.fixture
def maker(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'audit.db').as_posix()}", poolclass=NullPool
    )

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    asyncio.run(engine.dispose())


def step(maker, body):
    """Run one step in a FRESH session so nothing is served from a stale cache."""

    async def main():
        async with maker() as db:
            await body(db)

    asyncio.run(main())


# --- hashing primitives -----------------------------------------------------
def test_canonical_json_is_order_independent():
    assert audit.canonical({"b": 1, "a": 2}) == audit.canonical({"a": 2, "b": 1})


def test_hash_changes_when_any_field_changes():
    base = dict(
        seq=1,
        at="2026-07-25T10:00:00+00:00",
        kind="scan",
        actor="app",
        target="t",
        outcome="ok",
        detail="{}",
        prev=audit.GENESIS,
    )
    h = audit.compute_hash(**base)
    for field, value in [
        ("seq", 2),
        ("kind", "inventory"),
        ("actor", "user"),
        ("target", "u"),
        ("outcome", "failed"),
        ("detail", '{"x":1}'),
        ("prev", "f" * 64),
    ]:
        assert audit.compute_hash(**{**base, field: value}) != h, field


def test_field_names_are_hashed_so_shifting_text_cannot_collide():
    """'ab'+'c' and 'a'+'bc' across two adjacent fields must not hash alike."""
    a = audit.compute_hash(
        seq=1, at="t", kind="ab", actor="c", target="", outcome="ok", detail="{}", prev=""
    )
    b = audit.compute_hash(
        seq=1, at="t", kind="a", actor="bc", target="", outcome="ok", detail="{}", prev=""
    )
    assert a != b


# --- secrets never land in the log -----------------------------------------
def test_secret_keys_are_redacted_before_hashing():
    cleaned = audit._strip_secrets(
        {"username": "dell", "password": "hunter2", "nested": {"api_key": "sk-1"}, "port": 5985}
    )
    assert cleaned["password"] == "[redacted]"
    assert cleaned["nested"]["api_key"] == "[redacted]"
    assert cleaned["username"] == "dell"  # identity is evidence; the secret is not
    assert cleaned["port"] == 5985


# --- the chain, end to end --------------------------------------------------
def test_chain_links_and_verifies(maker):
    async def body(db):
        first = await audit.record(db, "scan", target="192.168.3.0/24")
        second = await audit.record(db, "inventory", target="this-pc", detail={"total": 3})
        assert first.seq == 1 and first.prev_hash == audit.GENESIS
        assert second.seq == 2 and second.prev_hash == first.entry_hash
        assert await audit.verify(db) == {
            "ok": True,
            "entries": 2,
            "broken_at": None,
            "reason": "",
        }

    step(maker, body)


def test_editing_an_entry_is_detected(maker):
    """The realistic tampering case: quietly change one row's contents."""

    async def seed(db):
        await audit.record(db, "scan", target="a")
        await audit.record(db, "update_install", target="this-pc", outcome="failed")
        await audit.record(db, "scan", target="b")

    async def tamper(db):
        # Rewrite entry 2 while leaving its stored hash untouched.
        await db.execute(text("UPDATE audit_events SET outcome='ok' WHERE seq=2"))
        await db.commit()

    async def check(db):
        result = await audit.verify(db)
        assert result["ok"] is False
        assert result["broken_at"] == 2
        assert "do not match its hash" in result["reason"]

    step(maker, seed)
    step(maker, tamper)
    step(maker, check)


def test_deleting_an_entry_is_detected(maker):
    async def seed(db):
        for i in range(3):
            await audit.record(db, "scan", target=f"t{i}")

    async def tamper(db):
        await db.execute(text("DELETE FROM audit_events WHERE seq=2"))
        await db.commit()

    async def check(db):
        result = await audit.verify(db)
        assert result["ok"] is False
        assert result["broken_at"] == 3, "the gap must be caught at the next entry"
        assert "sequence gap" in result["reason"]

    step(maker, seed)
    step(maker, tamper)
    step(maker, check)


def test_rewriting_prev_hash_is_detected(maker):
    async def seed(db):
        await audit.record(db, "scan", target="a")
        await audit.record(db, "scan", target="b")

    async def tamper(db):
        await db.execute(text("UPDATE audit_events SET prev_hash=:h WHERE seq=2"), {"h": "a" * 64})
        await db.commit()

    async def check(db):
        result = await audit.verify(db)
        assert result["ok"] is False
        assert "prev_hash" in result["reason"]

    step(maker, seed)
    step(maker, tamper)
    step(maker, check)


def test_empty_chain_verifies_as_ok(maker):
    async def body(db):
        assert (await audit.verify(db))["ok"] is True

    step(maker, body)


def test_digest_pins_the_head(maker):
    async def body(db):
        empty = await audit.digest(db)
        assert empty["entries"] == 0 and empty["head_hash"] == audit.GENESIS
        entry = await audit.record(db, "scan", target="x")
        full = await audit.digest(db)
        assert full["entries"] == 1
        assert full["head_seq"] == 1
        assert full["head_hash"] == entry.entry_hash

    step(maker, body)


def test_credential_use_records_the_use_not_the_credential(maker):
    async def body(db):
        await audit.record(
            db,
            "credential_use",
            target="192.168.3.133",
            detail={"username": "dell", "password": "hunter2", "transport": "ntlm"},
        )
        row = (await db.execute(select(AuditEventORM))).scalars().one()
        stored = json.loads(row.detail)
        assert stored["username"] == "dell"
        assert stored["password"] == "[redacted]"
        assert "hunter2" not in row.detail

    step(maker, body)


@pytest.mark.parametrize("kind", ["scan", "inventory", "cve_check", "update_install"])
def test_kinds_round_trip(maker, kind):
    async def body(db):
        await audit.record(db, kind)
        rows = (await db.execute(select(AuditEventORM))).scalars().all()
        assert rows[0].kind == kind

    step(maker, body)


# --- endpoints --------------------------------------------------------------
def test_endpoints_expose_read_verify_digest(client):
    r = client.get("/api/audit/events")
    assert r.status_code == 200 and r.json() == {"events": [], "returned": 0}
    assert client.get("/api/audit/verify").json()["ok"] is True
    assert client.get("/api/audit/digest").json()["entries"] == 0


def test_there_is_no_write_endpoint(client):
    """An API that could edit the trail would defeat its purpose."""
    for method, path in [
        ("post", "/api/audit/events"),
        ("delete", "/api/audit/events"),
        ("post", "/api/audit/verify"),
    ]:
        resp = getattr(client, method)(path, headers=CSRF)
        assert resp.status_code in (404, 405), f"{method} {path} must not exist"


def test_real_operations_write_audit_entries(client, monkeypatch):
    """Wiring check: an inventory refresh and a settings change must both appear."""
    from app.services import software_updates as sw

    async def fake_list():
        return [sw.InstalledSoftwareInfo("A.One", "One", "1.0")], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    assert client.post("/api/updates/inventory/refresh", headers=CSRF).status_code == 200
    assert (
        client.post(
            "/api/system/settings", json={"scan_method": "python"}, headers=CSRF
        ).status_code
        == 200
    )

    kinds = [e["kind"] for e in client.get("/api/audit/events").json()["events"]]
    assert "inventory" in kinds
    assert "settings_change" in kinds
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_audit_failure_never_breaks_the_audited_operation(client, monkeypatch):
    """A broken log must not roll back a real inventory/patch run."""

    async def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(audit, "record", boom)
    from app.services import software_updates as sw

    async def fake_list():
        return [sw.InstalledSoftwareInfo("A.One", "One", "1.0")], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF)
    assert r.status_code == 200, "the operation must still succeed"
    assert r.json()["total"] == 1
