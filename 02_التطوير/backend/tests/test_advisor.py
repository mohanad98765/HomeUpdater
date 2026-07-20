"""AI Advisor tests — endpoint gating + the agentic tool loop (Claude mocked)."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.orm import Base, DeviceORM
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
    r = client.post("/api/advisor/analyze", json={"lang": "en"}, headers=CSRF)
    assert r.status_code == 503


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

    # Turn 1: Claude calls list_devices. Turn 2: it answers.
    responses = [
        _Resp("tool_use", [_Block(type="tool_use", name="list_devices", id="t1", input={})]),
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
    assert result["trace"] == [{"tool": "list_devices"}]
    # tool_result was fed back → two model calls, and the tool ran against real data.
    assert len(fake.messages.calls) == 2
    # the assistant turn (with tool_use) plus the tool_result user turn were appended.
    assert any(m["role"] == "user" for m in fake.messages.calls[1]["messages"])
