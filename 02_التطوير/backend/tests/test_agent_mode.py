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
        # Since the protocol change the check-in carries the ITEMS, not just how many —
        # that is what lets the hub name an update the agent will actually accept.
        return {
            "inventory_count": 2,
            "pending_updates": 1,
            "updates": [
                {
                    "id": "KB5000001",
                    "title": "Security Update for Windows",
                    "kind": "windows",
                    "severity": "Critical",
                    "size_mb": 42.5,
                    "requires_reboot": True,
                }
            ],
            "packages": [
                {
                    "id": "7zip.7zip",
                    "name": "7-Zip",
                    "current_version": "21.07",
                    "available_version": "24.09",
                }
            ],
            "truncated": False,
            "known_updates": ["KB5000001"],
            "known_products": ["7zip.7zip", "Git.Git"],
        }

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


# --- the protocol change: the hub learns WHICH, not just how many --------------------
def test_the_hub_now_knows_which_updates_a_machine_has(client, enrolled):
    """Before this, a check-in carried two integers. The hub could see that a machine
    had eleven updates and could never name one — and the agent refuses any id it did
    not itself report, so every remote install it issued failed by construction."""
    import asyncio

    asyncio.run(agent_mode.run_once(enrolled, client))

    agent_id = client.get("/api/agents").json()["agents"][0]["id"]
    items = client.get(f"/api/agents/{agent_id}/items").json()
    assert [u["item_id"] for u in items["updates"]] == ["KB5000001"]
    assert items["updates"][0]["title"] == "Security Update for Windows"
    assert items["updates"][0]["requires_reboot"] is True
    assert [p["item_id"] for p in items["packages"]] == ["7zip.7zip"]
    assert items["packages"][0]["available_version"] == "24.09"
    assert items["truncated"] is False
    assert items["reported_at"]


def test_a_command_named_from_that_list_is_accepted_and_runs(client, enrolled, monkeypatch):
    """The whole point: the operator picks from what the machine reported, and the
    machine accepts it because it is its own id."""
    import asyncio

    installed = {}

    async def fake_install(ids):
        installed["ids"] = list(ids)
        return {"installed": len(ids), "requested": len(ids), "reboot_required": False}

    monkeypatch.setattr("app.services.windows_updates.install_updates", fake_install)

    asyncio.run(agent_mode.run_once(enrolled, client))
    agent_id = client.get("/api/agents").json()["agents"][0]["id"]
    reported = client.get(f"/api/agents/{agent_id}/items").json()
    chosen = [reported["updates"][0]["item_id"]]

    queued = client.post(
        f"/api/agents/{agent_id}/command",
        headers={"X-HomeUpdater": "1"},
        json={"kind": "windows_updates_install", "update_ids": chosen},
    )
    assert queued.status_code == 200, queued.text

    asyncio.run(agent_mode.run_once(enrolled, client))
    assert installed["ids"] == chosen, "the remote install actually ran"


def test_the_agent_still_refuses_an_id_the_hub_invented(client, enrolled, monkeypatch):
    """Reporting the ids must not weaken the guard that made the protocol safe: a hub
    that has been taken over must not be able to name an update this machine never saw."""
    import asyncio

    async def must_not_run(ids):
        raise AssertionError(f"the agent ran an id it never reported: {ids}")

    monkeypatch.setattr("app.services.windows_updates.install_updates", must_not_run)

    asyncio.run(agent_mode.run_once(enrolled, client))
    agent_id = client.get("/api/agents").json()["agents"][0]["id"]
    client.post(
        f"/api/agents/{agent_id}/command",
        headers={"X-HomeUpdater": "1"},
        json={"kind": "windows_updates_install", "update_ids": ["KB-NEVER-REPORTED"]},
    )
    asyncio.run(agent_mode.run_once(enrolled, client))

    commands = client.get(f"/api/agents/{agent_id}/commands").json()["commands"]
    # It reports the refusal rather than acting on it — and the status is not "done",
    # because a refused command did not do what was asked.
    assert commands, "the command must be accounted for, not vanish"
    assert "refused" in (commands[-1]["result"] or ""), commands[-1]
    assert commands[-1]["status"] != "done"


def test_the_snapshot_replaces_rather_than_accumulates(client, enrolled, monkeypatch):
    """A check-in is a snapshot. Merging would leave ghosts: an update installed by
    Windows itself would stay on the hub's list, the operator would try it, and the
    agent would refuse — a failure nobody could explain."""
    import asyncio

    asyncio.run(agent_mode.run_once(enrolled, client))

    async def fewer():
        return {
            "inventory_count": 2,
            "pending_updates": 0,
            "updates": [],
            "packages": [],
            "truncated": False,
            "known_updates": [],
            "known_products": ["7zip.7zip"],
        }

    monkeypatch.setattr(agent_mode, "_collect", fewer)
    asyncio.run(agent_mode.run_once(enrolled, client))

    agent_id = client.get("/api/agents").json()["agents"][0]["id"]
    items = client.get(f"/api/agents/{agent_id}/items").json()
    assert items["updates"] == [] and items["packages"] == []


def test_a_machine_with_more_than_one_body_holds_says_so(client, enrolled, monkeypatch):
    import asyncio

    async def lots():
        return {
            "inventory_count": 5000,
            "pending_updates": 5000,
            "updates": [{"id": f"KB{i}", "title": f"u{i}", "kind": "windows"} for i in range(200)],
            "packages": [],
            "truncated": True,
            "known_updates": [f"KB{i}" for i in range(5000)],
            "known_products": [],
        }

    monkeypatch.setattr(agent_mode, "_collect", lots)
    asyncio.run(agent_mode.run_once(enrolled, client))
    agent_id = client.get("/api/agents").json()["agents"][0]["id"]
    items = client.get(f"/api/agents/{agent_id}/items").json()
    assert items["truncated"] is True, "a partial list must not read as the whole state"
    assert len(items["updates"]) == 200
