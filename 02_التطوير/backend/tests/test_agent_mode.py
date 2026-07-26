"""``--agent`` mode — the target side, tested against the real hub endpoints.

The agent is the component that will run as LOCAL SYSTEM on other people's machines,
so the tests that matter are the ones where the HUB misbehaves: these check that the
agent refuses work it cannot justify, rather than trusting whatever came back.

The hub here is the actual FastAPI app via the test client, so the signing, the nonce
store and the command enumeration are all exercised end to end — a mocked hub would
mostly test the mock.
"""

from __future__ import annotations

import json

import pytest

from app import agent_mode
from app.services import enrolment


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Keep the agent's state file out of the developer's real app data."""
    monkeypatch.setattr(agent_mode, "get_appdata_dir", lambda: tmp_path)
    enrolment.reset_for_tests()
    yield
    enrolment.reset_for_tests()


def _enrol(client, *, bound=True, machine="agent-machine"):
    monkey_id = machine
    token = enrolment.mint(
        target_hint="SRV-AGENT",
        machine_id=monkey_id if bound else None,
        allow_any_machine=not bound,
    ).token
    return token


# --- enrolment ---------------------------------------------------------------
def test_enrol_stores_state_and_never_writes_the_key_in_clear(client, monkeypatch, tmp_path):
    monkeypatch.setattr(agent_mode, "machine_id", lambda: "agent-machine")
    token = _enrol(client)
    state, body = agent_mode.enrol("http://127.0.0.1", token, name="SRV-AGENT", client=client)

    assert body["status"] == "active"
    assert state.agent_id == body["agent_id"]
    on_disk = (tmp_path / agent_mode.STATE_FILE).read_text(encoding="utf-8")
    assert "BEGIN PRIVATE KEY" not in on_disk, "the key must be encrypted at rest"
    assert state.key is not None, "…and still usable through the app's own crypto"


def test_enrol_reports_a_pending_enrolment(client, monkeypatch, caplog):
    monkeypatch.setattr(agent_mode, "machine_id", lambda: "agent-machine")
    token = _enrol(client, bound=False)
    _state, body = agent_mode.enrol("http://127.0.0.1", token, client=client)
    assert body["requires_confirmation"] is True


def test_enrolment_failure_is_raised_not_swallowed(client, monkeypatch):
    monkeypatch.setattr(agent_mode, "machine_id", lambda: "someone-elses-machine")
    token = _enrol(client, machine="the-real-target")
    with pytest.raises(agent_mode.AgentError, match="enrolment refused"):
        agent_mode.enrol("http://127.0.0.1", token, client=client)


# --- the transport rules the agent enforces on ITSELF ------------------------
def test_a_remote_hub_over_plain_http_is_refused():
    """Loopback http is for testing. Anything else must be https, or there is no
    channel security at all and the pin is meaningless."""
    with pytest.raises(agent_mode.AgentError, match="must use https"):
        agent_mode._require_pin_or_loopback("http://192.168.1.50:8000", "")


def test_https_without_a_pin_is_refused():
    with pytest.raises(agent_mode.AgentError, match="requires a certificate pin"):
        agent_mode._require_pin_or_loopback("https://hub.example.com", "")


def test_a_changed_certificate_stops_the_agent(monkeypatch):
    """Trusting a new certificate on sight would undo the pin — the agent stops and
    says so instead."""
    state = agent_mode.AgentState(
        hub_url="https://hub.example.com",
        agent_id="a",
        private_key_pem="x",
        cert_pin_sha256="a" * 64,
    )
    monkeypatch.setattr(agent_mode, "cert_fingerprint", lambda _url: "b" * 64)
    with pytest.raises(agent_mode.AgentError, match="certificate changed"):
        agent_mode.make_client(state)


# --- check-in and commands ---------------------------------------------------
@pytest.fixture
def enrolled(client, monkeypatch):
    monkeypatch.setattr(agent_mode, "machine_id", lambda: "agent-machine")

    # Keep the tests off this machine's real winget/WUA: the point here is the
    # protocol, and a real inventory would make them slow and machine-dependent.
    async def fake_collect():
        return 2, 1, ["KB5000001"], ["7zip.7zip", "Git.Git"]

    monkeypatch.setattr(agent_mode, "_collect", fake_collect)
    token = _enrol(client)
    state, _ = agent_mode.enrol("http://127.0.0.1", token, name="SRV-AGENT", client=client)
    return state


def test_checkin_reports_counts_and_is_signed(client, enrolled):
    import asyncio

    data = asyncio.run(agent_mode.run_once(enrolled, client))
    assert data["status"] == "active"
    row = client.get("/api/agents").json()["agents"][0]
    assert row["inventory_count"] == 2 and row["pending_updates"] == 1
    assert row["last_seen"] is not None


def test_a_queued_command_is_executed_and_reported(client, enrolled, monkeypatch):
    import asyncio

    async def fake_install(ids):
        return {"installed": len(ids), "reboot_required": False}

    monkeypatch.setattr("app.services.windows_updates.install_updates", fake_install)
    client.post(
        f"/api/agents/{enrolled.agent_id}/command",
        json={"kind": "windows_updates_install", "update_ids": ["KB5000001"]},
        headers={"X-HomeUpdater": "1"},
    )
    asyncio.run(agent_mode.run_once(enrolled, client))
    cmd = client.get(f"/api/agents/{enrolled.agent_id}/commands").json()["commands"][0]
    assert cmd["status"] == "done"
    assert cmd["result"] == "installed 1/1"


def test_the_agent_refuses_an_update_id_it_never_reported(client, enrolled, monkeypatch):
    """A hub naming an update this machine never saw is a bug or an attack; either way
    the agent is not the place to find out. It reports the refusal — it does not act."""
    import asyncio

    called = False

    async def must_not_run(ids):
        nonlocal called
        called = True
        return {"installed": 0}

    monkeypatch.setattr("app.services.windows_updates.install_updates", must_not_run)
    client.post(
        f"/api/agents/{enrolled.agent_id}/command",
        json={"kind": "windows_updates_install", "update_ids": ["KB-NEVER-SEEN"]},
        headers={"X-HomeUpdater": "1"},
    )
    asyncio.run(agent_mode.run_once(enrolled, client))
    assert called is False, "the agent executed an id it had not reported"
    cmd = client.get(f"/api/agents/{enrolled.agent_id}/commands").json()["commands"][0]
    assert cmd["status"] == "failed"
    assert "refused: unknown update ids" in cmd["result"]


def test_an_unknown_command_kind_is_refused_locally_too(enrolled):
    """Defence in depth: the hub enumerates kinds, and so does the agent. A hub that
    is compromised or simply newer must not make an old agent improvise."""
    import asyncio

    outcome = asyncio.run(
        agent_mode.execute({"id": 1, "kind": "run_shell", "cmd": "whoami"}, [], [])
    )
    assert outcome["ok"] is False
    assert "unknown command kind" in outcome["summary"]


def test_a_revoked_agent_stops_working_and_says_why(client, enrolled):
    import asyncio

    client.post(f"/api/agents/{enrolled.agent_id}/revoke", headers={"X-HomeUpdater": "1"})
    with pytest.raises(agent_mode.AgentError, match="check-in refused: 403"):
        asyncio.run(agent_mode.run_once(enrolled, client))


def test_signed_requests_carry_no_reusable_secret(client, enrolled):
    """The wire carries a signature, never the key: capturing a request must not let
    the capturer produce the next one."""
    body = json.dumps({"inventory_count": 1}).encode()
    headers = agent_mode.sign_headers(enrolled, "POST", "/api/agents/checkin", body)
    assert set(headers) >= {"X-HU-Agent", "X-HU-Timestamp", "X-HU-Nonce", "X-HU-Signature"}
    joined = json.dumps(headers)
    assert "PRIVATE KEY" not in joined
    assert enrolled.private_key_pem not in joined


# --- the CLI -----------------------------------------------------------------
def test_cli_without_enrolment_fails_with_a_usable_message(monkeypatch):
    monkeypatch.setattr(agent_mode, "load_state", lambda: None)
    assert agent_mode.main(["--agent"]) == 2


def test_cli_token_without_hub_is_refused(monkeypatch):
    monkeypatch.setattr(agent_mode, "load_state", lambda: None)
    assert agent_mode.main(["--agent", "--token", "HUENROL1.x.y"]) == 2
