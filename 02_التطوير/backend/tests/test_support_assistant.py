"""In-app support assistant (services/support_assistant + POST /api/advisor/support).

Scoped to app help, no DB, no network-data consent, and its OWN lock so it stays
usable during a network analysis. Claude is mocked with a scripted fake client.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import advisor, support_assistant


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, model="claude-opus-4-8"):
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


def _wire(monkeypatch, responses, *, key="sk-test"):
    import anthropic

    monkeypatch.setattr(advisor, "get_api_key", lambda: key)
    fake = _FakeClient(responses)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: fake)
    return fake


def _ask(question="How do I scan my network?"):
    return support_assistant.support_chat([{"role": "user", "content": question}])


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(advisor, "get_api_key", lambda: "")
    with pytest.raises(support_assistant.SupportError, match="not configured"):
        asyncio.run(_ask())


def test_returns_reply_and_uses_the_support_scope(monkeypatch):
    fake = _wire(monkeypatch, [_Resp([_Block(type="text", text="Open the Devices page and scan.")])])
    result = asyncio.run(_ask())
    assert result["reply"] == "Open the Devices page and scan."
    assert result["model"] == "claude-opus-4-8"
    # The request must carry the app-scoped system prompt (not the advisor's) and
    # send NO tools (this assistant never touches the network DB).
    sent = fake.messages.calls[0]
    assert sent["system"] == support_assistant._SUPPORT_SYSTEM
    assert "HomeUpdater" in sent["system"]
    assert "tools" not in sent


def test_empty_reply_raises(monkeypatch):
    _wire(monkeypatch, [_Resp([_Block(type="text", text="   ")])])
    with pytest.raises(support_assistant.SupportError, match="empty"):
        asyncio.run(_ask())


def test_empty_history_raises(monkeypatch):
    _wire(monkeypatch, [])
    with pytest.raises(support_assistant.SupportError):
        asyncio.run(support_assistant.support_chat([{"role": "assistant", "content": "hi"}]))


def test_busy_lock_raises(monkeypatch):
    _wire(monkeypatch, [])  # client never reached — the lock check precedes it

    async def run():
        await support_assistant._support_lock.acquire()
        try:
            with pytest.raises(support_assistant.SupportError, match="busy|مشغول"):
                await _ask()
        finally:
            support_assistant._support_lock.release()

    asyncio.run(run())


def test_independent_of_advisor_lock(monkeypatch):
    # Holding the ADVISOR lock must NOT block the support assistant (separate lock).
    _wire(monkeypatch, [_Resp([_Block(type="text", text="Sure — here is how.")])])

    async def run():
        await advisor._advisor_lock.acquire()
        try:
            result = await _ask()
            assert result["reply"] == "Sure — here is how."
        finally:
            advisor._advisor_lock.release()

    asyncio.run(run())


# --- endpoint ---------------------------------------------------------------
def test_support_endpoint_400_on_empty(client):
    r = client.post("/api/advisor/support", json={"messages": []}, headers={"X-HomeUpdater": "1"})
    assert r.status_code == 400


def test_support_endpoint_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(advisor, "get_api_key", lambda: "")
    r = client.post(
        "/api/advisor/support",
        json={"messages": [{"role": "user", "content": "how do I add a WinRM host?"}]},
        headers={"X-HomeUpdater": "1"},
    )
    assert r.status_code == 503


def test_support_endpoint_returns_reply(client, monkeypatch):
    _wire(monkeypatch, [_Resp([_Block(type="text", text="Open Windows Remote and click add.")])])
    r = client.post(
        "/api/advisor/support",
        json={"messages": [{"role": "user", "content": "how do I add a WinRM host?"}]},
        headers={"X-HomeUpdater": "1"},
    )
    assert r.status_code == 200
    assert r.json()["reply"] == "Open Windows Remote and click add."
