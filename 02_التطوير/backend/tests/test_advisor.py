"""AI Advisor tests — endpoint gating + the agentic tool loop (Claude mocked)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.orm import Base, DeviceORM, SoftwarePackageORM, WinRMHostORM
from app.services import advisor

CSRF = {"X-HomeUpdater": "1"}


def test_status_unconfigured(client, monkeypatch):
    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "")
    monkeypatch.setattr(advisor, "get_api_key", lambda: "")
    r = client.get("/api/advisor/status")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_analyze_requires_key(client, monkeypatch):
    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "")
    monkeypatch.setattr(advisor, "get_api_key", lambda: "")
    monkeypatch.setattr(advisor, "has_consent", lambda: True)  # consent given → key check runs
    r = client.post("/api/advisor/analyze", json={"lang": "en"}, headers=CSRF)
    assert r.status_code == 503


def test_analyze_blocked_without_consent(client, monkeypatch):
    """T11: the data-sharing consent gate precedes everything (even the key check)."""
    monkeypatch.setattr(advisor, "has_consent", lambda: False)
    r = client.post("/api/advisor/analyze", json={"lang": "en"}, headers=CSRF)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "consent_required"


def test_key_saved_encrypted_roundtrip(monkeypatch, tmp_path):
    """A UI-saved key round-trips and is stored encrypted, not in plaintext."""
    from cryptography.fernet import Fernet

    from app import crypto

    monkeypatch.setenv("HOMEUPDATER_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "")
    monkeypatch.setattr(advisor, "get_data_dir", lambda: tmp_path)
    crypto.reset_cache()

    advisor.set_api_key("sk-ant-secret-123")
    assert advisor.get_api_key() == "sk-ant-secret-123"
    assert advisor.is_configured() is True

    on_disk = (tmp_path / "advisor_key.enc").read_text(encoding="utf-8")
    assert "sk-ant-secret-123" not in on_disk  # ciphertext, not plaintext
    assert on_disk.startswith("gAAAAA")  # Fernet token

    advisor.set_api_key("")  # clear
    assert advisor.get_api_key() == ""
    assert not (tmp_path / "advisor_key.enc").exists()
    crypto.reset_cache()


# --- the agentic loop, with a fake Claude client -------------------------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, stop_reason, content, model="claude-opus-4-8"):
        self.stop_reason = stop_reason
        self.content = content
        self.model = model


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_agentic_loop(monkeypatch, tmp_path):
    import anthropic

    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "sk-test")

    # Turn 1: list_devices. Turn 2: set_plan (the structured plan). Turn 3: answer.
    responses = [
        _Resp("tool_use", [_Block(type="tool_use", name="list_devices", id="t1", input={})]),
        _Resp(
            "tool_use",
            [
                _Block(
                    type="tool_use",
                    name="set_plan",
                    id="t2",
                    input={"actions": [{"type": "app", "id": "Foo.Bar", "title": "Foo 2.0"}]},
                )
            ],
        ),
        _Resp("end_turn", [_Block(type="text", text="Update the router first (critical).")]),
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: fake)

    async def run():
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'adv.db').as_posix()}"
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            db.add(DeviceORM(ip="192.168.1.1", vendor="TP-Link", device_type="router"))
            await db.commit()
            result = await advisor.analyze(db, lang_hint="en")
        await engine.dispose()
        return result

    result = asyncio.run(run())
    assert "router" in result["recommendations"].lower()
    assert result["trace"] == [{"tool": "list_devices"}, {"tool": "set_plan"}]
    # the set_plan tool's actions are captured and returned for one-click apply.
    assert result["actions"] == [{"type": "app", "id": "Foo.Bar", "title": "Foo 2.0"}]
    assert len(fake.messages.calls) == 3
    # the assistant turn (with tool_use) plus the tool_result user turn were appended.
    assert any(m["role"] == "user" for m in fake.messages.calls[1]["messages"])


def test_chat_uses_readonly_tools(monkeypatch, tmp_path):
    """Chat answers via the read-only tools and never exposes set_plan."""
    import anthropic

    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "sk-test")
    responses = [
        _Resp("tool_use", [_Block(type="tool_use", name="list_devices", id="c1", input={})]),
        _Resp("end_turn", [_Block(type="text", text="You have 1 device: the router.")]),
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: fake)

    async def run():
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'chat.db').as_posix()}"
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            db.add(DeviceORM(ip="192.168.1.1", vendor="TP-Link", device_type="router"))
            await db.commit()
            res = await advisor.chat(db, [{"role": "user", "content": "how many devices?"}])
        await engine.dispose()
        return res

    result = asyncio.run(run())
    assert "device" in result["reply"].lower()
    assert result["trace"] == [{"tool": "list_devices"}]
    tools_sent = fake.messages.calls[0]["tools"]
    assert all(t["name"] != "set_plan" for t in tools_sent)  # read-only in chat
    assert any(t["name"] == "list_devices" for t in tools_sent)


def test_apply_plan_only_installs_pending(monkeypatch, tmp_path):
    """apply_plan installs only genuinely-pending ids; unknown/stale ids are skipped."""
    from app.services import software_updates, windows_updates

    called: dict = {}

    async def fake_install_many(ids):
        called["app"] = list(ids)
        return {
            "installed": len(ids),
            "total": len(ids),
            "results": [{"package_id": i, "exit_code": 0, "succeeded": True} for i in ids],
        }

    async def fake_install_updates(ids):
        called["win"] = list(ids)
        return {"installed": len(ids), "total": len(ids)}

    monkeypatch.setattr(software_updates, "install_many", fake_install_many)
    monkeypatch.setattr(windows_updates, "install_updates", fake_install_updates)

    async def run():
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'apply.db').as_posix()}"
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            db.add(
                SoftwarePackageORM(
                    package_id="Real.App", available_version="2.0", is_installed=False
                )
            )
            db.add(
                SoftwarePackageORM(
                    package_id="Done.App", available_version="1.0", is_installed=True
                )
            )
            await db.commit()
            res = await advisor.apply_plan(
                db,
                [
                    {"type": "app", "id": "Real.App", "title": "Real"},  # pending → install
                    {"type": "app", "id": "Done.App", "title": "Done"},  # installed → skip
                    {"type": "app", "id": "Ghost.App", "title": "Ghost"},  # unknown → skip
                ],
            )
            # the succeeded package is now marked installed (won't re-trigger)
            row = (
                await db.execute(
                    select(SoftwarePackageORM).where(SoftwarePackageORM.package_id == "Real.App")
                )
            ).scalar_one()
            installed_after = row.is_installed
        await engine.dispose()
        return res, installed_after

    result, installed_after = asyncio.run(run())
    assert called["app"] == ["Real.App"]  # ONLY the genuinely-pending package
    assert result["applied"] == 1
    assert set(result["skipped"]) == {"Done.App", "Ghost.App"}
    assert installed_after is True  # DB write-back persisted


def test_apply_plan_remote_only_configured_hosts(monkeypatch, tmp_path):
    """Remote apply upgrades ONLY configured hosts; unknown host ids are skipped."""
    from app.services import winrm_hosts as winrm_svc

    called: dict = {}

    async def fake_apply(host, *a, **k):
        called.setdefault("hosts", []).append(host)
        return {"succeeded": True, "output_tail": "ok"}

    monkeypatch.setattr(winrm_svc, "apply_updates", fake_apply)

    async def run():
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'remote.db').as_posix()}"
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            db.add(WinRMHostORM(host="10.0.0.5", username="Admin"))  # id=1
            await db.commit()
            res = await advisor.apply_plan(
                db,
                [
                    {"type": "winrm", "id": "1", "title": "upgrade 10.0.0.5"},  # configured
                    {"type": "winrm", "id": "999", "title": "ghost host"},  # unknown → skip
                ],
            )
        await engine.dispose()
        return res

    result = asyncio.run(run())
    assert called["hosts"] == ["10.0.0.5"]  # only the configured host was touched
    assert result["applied"] == 1
    assert "winrm:999" in result["skipped"]
    assert result["remote"][0]["ok"] is True


def test_apply_plan_malformed_remote_ids_are_skipped_not_500(monkeypatch, tmp_path):
    """Malformed remote ids (non-numeric, or Unicode digits int() rejects) must be
    reported as skipped — never crash apply_plan, never touch any host."""
    from app.services import winrm_hosts as winrm_svc

    async def fake_apply(host, *a, **k):  # pragma: no cover - must never run
        raise AssertionError(f"no host should be contacted, got {host}")

    monkeypatch.setattr(winrm_svc, "apply_updates", fake_apply)

    async def run():
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'malformed.db').as_posix()}"
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            res = await advisor.apply_plan(
                db,
                [
                    {"type": "winrm", "id": "living-room-pc", "title": "x"},  # non-numeric
                    {"type": "ssh", "id": "²", "title": "y"},  # '²' — isdigit() but not int()
                ],
            )
        await engine.dispose()
        return res

    result = asyncio.run(run())  # must not raise (no unhandled ValueError → no 500)
    assert result["applied"] == 0
    assert result["remote"] == []
    assert "winrm:living-room-pc" in result["skipped"]
    assert "ssh:²" in result["skipped"]
