"""Advisor agentic-loop failure & guard paths (advisor._run_agent via analyze()).

test_advisor.py covers the happy path; this file locks down the robustness
contract of the paid Opus loop: refusal, empty answer, non-convergence, tool
failure isolation, max_tokens truncation, the busy lock, and the deadline.
Claude is mocked with a scripted fake client (same shape as test_advisor.py).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.orm import Base, DeviceORM
from app.services import advisor


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


def _wire(monkeypatch, responses):
    """Configure a key + a scripted fake Claude client; return the fake."""
    import anthropic

    monkeypatch.setattr(advisor.settings, "anthropic_api_key", "sk-test")
    fake = _FakeClient(responses)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: fake)
    return fake


def _analyze(responses, monkeypatch, tmp_path):
    """Run advisor.analyze() against a fresh 1-device db with scripted responses."""
    _wire(monkeypatch, responses)

    async def run():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'loop.db').as_posix()}", poolclass=NullPool
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with Session() as db:
                db.add(DeviceORM(ip="192.168.1.1", vendor="TP-Link", device_type="router"))
                await db.commit()
                return await advisor.analyze(db, lang_hint="en")
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_refusal_raises(monkeypatch, tmp_path):
    with pytest.raises(advisor.AdvisorError, match="declined"):
        _analyze([_Resp("refusal", [])], monkeypatch, tmp_path)


def test_empty_answer_raises(monkeypatch, tmp_path):
    with pytest.raises(advisor.AdvisorError, match="empty"):
        _analyze([_Resp("end_turn", [_Block(type="text", text="   ")])], monkeypatch, tmp_path)


def test_non_convergence_raises(monkeypatch, tmp_path):
    # _MAX_ROUNDS consecutive tool_use turns, never a final answer.
    responses = [
        _Resp("tool_use", [_Block(type="tool_use", name="list_devices", id=f"t{i}", input={})])
        for i in range(advisor._MAX_ROUNDS)
    ]
    with pytest.raises(advisor.AdvisorError, match="did not converge"):
        _analyze(responses, monkeypatch, tmp_path)


def test_tool_failure_is_surfaced_not_raised(monkeypatch, tmp_path):
    """A tool blowing up is caught and fed back to the model, not 500'd."""

    async def boom(_db):
        raise RuntimeError("db exploded")

    monkeypatch.setitem(advisor._DISPATCH, "list_devices", boom)
    responses = [
        _Resp("tool_use", [_Block(type="tool_use", name="list_devices", id="t1", input={})]),
        _Resp("end_turn", [_Block(type="text", text="Recovered fine.")]),
    ]
    result = _analyze(responses, monkeypatch, tmp_path)  # must NOT raise
    assert result["recommendations"] == "Recovered fine."
    assert result["trace"] == [{"tool": "list_devices"}]


def test_max_tokens_sets_truncated(monkeypatch, tmp_path):
    result = _analyze(
        [_Resp("max_tokens", [_Block(type="text", text="Partial plan.")])], monkeypatch, tmp_path
    )
    assert result["truncated"] is True
    assert result["recommendations"] == "Partial plan."


def test_busy_lock_raises(monkeypatch, tmp_path):
    _wire(monkeypatch, [])  # client never used — the lock check precedes it

    async def run():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'busy.db').as_posix()}", poolclass=NullPool
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        await advisor._advisor_lock.acquire()  # simulate an in-flight advisor call
        try:
            async with Session() as db:
                with pytest.raises(advisor.AdvisorError, match="busy|مشغول"):
                    await advisor.analyze(db, lang_hint="en")
        finally:
            advisor._advisor_lock.release()
            await engine.dispose()

    asyncio.run(run())


def test_deadline_overrun_raises(monkeypatch, tmp_path):
    # A past deadline forces the very first round to trip the overall time bound.
    monkeypatch.setattr(advisor, "_AGENT_DEADLINE", -1.0)
    with pytest.raises(advisor.AdvisorError, match="timed out|مهلة"):
        _analyze([_Resp("end_turn", [_Block(type="text", text="never")])], monkeypatch, tmp_path)
