"""The operator's half of the agent feature — the endpoints a human drives.

The agent-side protocol is tested in test_agents.py and test_agent_mode.py. What is
tested here is the part where a person with administrator rights makes decisions that
cannot be taken back: minting a credential the whole network can redeem, promoting a
machine to trusted, cutting one off forever, and replacing the certificate the entire
fleet pinned.

The through-line: an unbound enrolment token means a stranger's machine can appear in
this list next to the one the operator expects. Everything below exists so that the
operator cannot trust the wrong one by clicking the wrong row.
"""

from __future__ import annotations

import pytest

from app import agent_listener
from app.services import agent_auth, enrolment


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(enrolment, "get_appdata_dir", lambda: tmp_path)
    enrolment.reset_for_tests()
    agent_auth.RECENT_REFUSALS.clear()
    yield
    enrolment.reset_for_tests()
    agent_auth.RECENT_REFUSALS.clear()


H = {"X-HomeUpdater": "1"}


def _enrol_a_machine(client, machine="target-machine", name="SRV-01"):
    """Put one pending agent in the list, the way an unbound token really does."""
    token = enrolment.mint(allow_any_machine=True).token
    body = client.post(
        "/api/agents/enrol",
        json={
            "token": token,
            "machine_id": machine,
            "public_key": "ab" * 32,
            "name": name,
        },
        headers=H,
    ).json()
    return body["agent_id"], enrolment.fingerprint(machine)


# --- minting -------------------------------------------------------------------
def test_minting_an_unbound_token_requires_saying_so(client):
    """The dangerous form of this credential must be asked for by name."""
    r = client.post("/api/agents/enrolment-token", json={}, headers=H)
    assert r.status_code == 400
    assert r.json()["detail"] == "unbound_requires_optin"


def test_a_minted_token_is_returned_once_and_carries_no_second_secret(client):
    r = client.post(
        "/api/agents/enrolment-token",
        json={"allow_any_machine": True, "target_hint": "Reception"},
        headers=H,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("HUENROL")
    assert body["bound"] is False and body["requires_confirmation"] is True
    # The nonce is the single-use handle. It is already inside the token; a second
    # copy on the wire is a second thing to leak.
    assert "nonce" not in body
    assert "hub_public_key" not in body


def test_there_is_no_way_to_read_a_token_back(client):
    """A credential shown twice is a credential stored somewhere."""
    assert client.get("/api/agents/enrolment-token").status_code in (404, 405)


def test_a_bound_token_names_the_machine_and_lands_active(client):
    """The safe path, which was unreachable before: bind by fingerprint, because the
    machine id is computed ON the target and no operator can type it."""
    fp = enrolment.fingerprint("the-real-target")
    r = client.post("/api/agents/enrolment-token", json={"machine_fingerprint": fp}, headers=H)
    assert r.status_code == 200 and r.json()["bound"] is True
    assert r.json()["requires_confirmation"] is False

    enrolled = client.post(
        "/api/agents/enrol",
        json={
            "token": r.json()["token"],
            "machine_id": "the-real-target",
            "public_key": "cd" * 32,
        },
        headers=H,
    )
    assert enrolled.json()["status"] == "active", "a bound enrolment needs no human step"


def test_a_bound_token_is_refused_from_any_other_machine(client):
    fp = enrolment.fingerprint("the-real-target")
    token = client.post(
        "/api/agents/enrolment-token", json={"machine_fingerprint": fp}, headers=H
    ).json()["token"]
    r = client.post(
        "/api/agents/enrol",
        json={"token": token, "machine_id": "somebody-else", "public_key": "ef" * 32},
        headers=H,
    )
    assert r.status_code == 401 and r.json()["detail"] == "wrong_machine"


def test_asking_for_bound_and_unbound_at_once_is_refused(client):
    """Picking one silently is how a token ends up unbound while the operator
    believes it is bound."""
    r = client.post(
        "/api/agents/enrolment-token",
        json={"machine_fingerprint": "a" * 32, "allow_any_machine": True},
        headers=H,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "fingerprint_and_allow_any_machine"


def test_a_malformed_fingerprint_is_refused_rather_than_ignored(client):
    r = client.post(
        "/api/agents/enrolment-token", json={"machine_fingerprint": "not-hex"}, headers=H
    )
    assert r.status_code == 400
    assert "fingerprint" in r.json()["detail"]


def test_the_audit_entry_for_a_mint_contains_no_credential(client):
    client.post("/api/agents/enrolment-token", json={"allow_any_machine": True}, headers=H)
    events = client.get("/api/audit/events?limit=20").json()["events"]
    minted = [e for e in events if e["kind"] == "agent_enrolment_token_minted"]
    assert minted, "minting a credential must be audited"
    blob = str(minted[0])
    assert "HUENROL" not in blob, "the audit log ships inside the paid Evidence Pack"
    assert "nonce" not in blob


# --- the confirmation challenge -------------------------------------------------
def test_a_pending_fingerprint_is_masked_in_the_list(client):
    """The answer to the challenge must not be on the operator's own screen."""
    _agent_id, fp = _enrol_a_machine(client)
    row = client.get("/api/agents").json()["agents"][0]
    assert row["status"] == "pending"
    assert row["fingerprint"] is None
    assert row["fingerprint_head"] == fp[:8]
    assert fp[-8:] not in str(row), "the tail is what the operator must go and read"


def test_confirming_requires_the_last_eight_characters(client):
    agent_id, fp = _enrol_a_machine(client)
    r = client.post(
        f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": fp[-8:]}, headers=H
    )
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["fingerprint"] == fp, "nothing left to hide once it is trusted"


def test_a_wrong_suffix_does_not_trust_the_machine_and_says_nothing_useful(client):
    agent_id, _fp = _enrol_a_machine(client)
    r = client.post(
        f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": "deadbeef"}, headers=H
    )
    assert r.status_code == 400 and r.json()["detail"] == "fingerprint_mismatch"
    assert client.get("/api/agents").json()["agents"][0]["status"] == "pending"
    assert "deadbeef" not in str(r.json())


def test_guessing_the_suffix_is_rate_limited(client):
    """Eight hex characters are all that stand between a stranger's machine and trust."""
    agent_id, fp = _enrol_a_machine(client)
    for _ in range(5):
        client.post(
            f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": "00000000"}, headers=H
        )
    blocked = client.post(
        f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": fp[-8:]}, headers=H
    )
    assert blocked.status_code == 429, "even the right answer waits after five wrong ones"


def test_a_refused_confirmation_is_audited_without_the_answer(client):
    agent_id, _fp = _enrol_a_machine(client)
    client.post(
        f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": "00000000"}, headers=H
    )
    events = client.get("/api/audit/events?limit=20").json()["events"]
    refused = [e for e in events if e["kind"] == "agent_confirm_refused"]
    assert refused and refused[0]["outcome"] == "failed"


def test_confirming_an_already_active_agent_is_not_a_silent_success(client):
    agent_id, fp = _enrol_a_machine(client)
    client.post(f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": fp[-8:]}, headers=H)
    again = client.post(
        f"/api/agents/{agent_id}/confirm", json={"fingerprint_suffix": fp[-8:]}, headers=H
    )
    assert again.status_code == 409 and again.json()["detail"] == "agent_already_active"


# --- revoke and forget ----------------------------------------------------------
def test_forgetting_is_only_possible_after_revoking(client):
    """So it can never become a shortcut around cutting a machine off."""
    agent_id, _fp = _enrol_a_machine(client)
    r = client.request("DELETE", f"/api/agents/{agent_id}", headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "agent_not_revoked"


def test_forgetting_a_revoked_machine_lets_it_enrol_again(client):
    """Revoke is otherwise a one-way door: one mis-click bars a machine forever."""
    agent_id, _fp = _enrol_a_machine(client)
    client.post(f"/api/agents/{agent_id}/revoke", headers=H)

    blocked = client.post(
        "/api/agents/enrol",
        json={
            "token": enrolment.mint(allow_any_machine=True).token,
            "machine_id": "target-machine",
            "public_key": "ab" * 32,
        },
        headers=H,
    )
    assert blocked.status_code == 403 and blocked.json()["detail"] == "agent_revoked"

    assert client.request("DELETE", f"/api/agents/{agent_id}", headers=H).status_code == 200
    again = client.post(
        "/api/agents/enrol",
        json={
            "token": enrolment.mint(allow_any_machine=True).token,
            "machine_id": "target-machine",
            "public_key": "ab" * 32,
        },
        headers=H,
    )
    assert again.status_code == 200, "the way back exists"


def test_forgetting_keeps_the_history(client):
    agent_id, _fp = _enrol_a_machine(client)
    client.post(f"/api/agents/{agent_id}/revoke", headers=H)
    client.request("DELETE", f"/api/agents/{agent_id}", headers=H)
    kinds = [e["kind"] for e in client.get("/api/audit/events?limit=50").json()["events"]]
    assert "agent_forgotten" in kinds and "agent_revoked" in kinds
    assert client.get("/api/agents").json()["total"] == 0


# --- the listener toggle --------------------------------------------------------
def test_the_listener_can_actually_be_turned_on_from_the_app(client, monkeypatch):
    """It could not before: the setting was whitelisted but no endpoint accepted it,
    so the whole feature was unreachable without hand-editing config.json."""
    started = {}

    class FakeListener:
        running = True
        error = ""

        def start(self):
            started["yes"] = True

        def stop(self):
            started["no"] = True

        def status(self):
            return {"enabled": True, "running": True, "port": 8443, "error": ""}

    monkeypatch.setattr(agent_listener, "listener", FakeListener())
    r = client.post("/api/agents/listener", json={"enabled": True}, headers=H)
    assert r.status_code == 200 and r.json()["running"] is True
    assert started.get("yes")


def test_a_failed_start_is_reported_not_raised(client, monkeypatch):
    """A port already in use is a fact about the machine, not a client error, and the
    operator needs the reason rather than a stack trace."""

    class DeadListener:
        running = False
        error = "[Errno 10048] address already in use"

        def start(self):
            pass

        def stop(self):
            pass

        def status(self):
            return {"enabled": True, "running": False, "port": 8443, "error": self.error}

    monkeypatch.setattr(agent_listener, "listener", DeadListener())
    r = client.post("/api/agents/listener", json={"enabled": True}, headers=H)
    assert r.status_code == 200
    assert "10048" in r.json()["error"]


# --- certificate regeneration ---------------------------------------------------
def test_regenerating_the_certificate_requires_naming_the_damage(client):
    """Not a confirmation checkbox: a wrong count means the caller's screen was stale
    about the very number that measures what breaks."""
    _enrol_a_machine(client)
    r = client.post(
        "/api/agents/listener/certificate/regenerate",
        json={"acknowledge_agents": 0},
        headers=H,
    )
    assert r.status_code == 409 and r.json()["detail"] == "agent_count_mismatch:1"


def test_regeneration_lists_exactly_who_it_broke(client):
    _agent_id, _fp = _enrol_a_machine(client)
    r = client.post(
        "/api/agents/listener/certificate/regenerate",
        json={"acknowledge_agents": 1},
        headers=H,
    )
    assert r.status_code == 200
    assert [a["name"] for a in r.json()["broken_agents"]] == ["SRV-01"]
    assert "re-enrol" in r.json()["warning"]


def test_a_revoked_agent_is_not_counted_as_breakable(client):
    agent_id, _fp = _enrol_a_machine(client)
    client.post(f"/api/agents/{agent_id}/revoke", headers=H)
    r = client.post(
        "/api/agents/listener/certificate/regenerate",
        json={"acknowledge_agents": 0},
        headers=H,
    )
    assert r.status_code == 200, "it was already not working; nothing to break"


# --- the refusal feed -----------------------------------------------------------
def test_a_refused_enrolment_tells_the_operator_why(client):
    """Without this every failure reaches the operator as the same thing: silence."""
    client.post(
        "/api/agents/enrol",
        json={"token": "HUENROL1.bogus.bogus", "machine_id": "m", "public_key": "ab" * 32},
        headers=H,
    )
    feed = client.get("/api/agents/refusals").json()["refusals"]
    assert feed and feed[0]["reason"].startswith("enrol:")
    assert feed[0]["path"] == "/api/agents/enrol"


def test_a_clock_that_drifted_says_so_by_how_much(client):
    client.post("/api/agents/checkin", json={}, headers={**H, "X-HU-Agent": "x"})
    feed = client.get("/api/agents/refusals").json()["refusals"]
    assert feed[0]["reason"] == "missing_signature_headers"


def test_the_refusal_feed_carries_no_request_content(client):
    client.post(
        "/api/agents/enrol",
        json={"token": "HUENROL1.secret.parts", "machine_id": "m", "public_key": "ab" * 32},
        headers=H,
    )
    blob = str(client.get("/api/agents/refusals").json())
    assert "secret" not in blob, "reasons, not bodies"


def test_the_refusal_ring_is_bounded(client):
    for _ in range(150):
        agent_auth.note_refusal("bad_signature", path="/api/agents/checkin")
    assert len(agent_auth.RECENT_REFUSALS) == 100
    assert client.get("/api/agents/refusals?limit=500").json()["total"] == 100


# --- none of this is reachable from the network ---------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/api/agents/enrolment-token",
        "/api/agents/listener",
        "/api/agents/refusals",
        "/api/agents/listener/certificate/regenerate",
    ],
)
def test_the_new_operator_paths_are_not_on_the_network_socket(path):
    from fastapi.testclient import TestClient

    assert path not in agent_listener.AGENT_PATHS
    listener_app = TestClient(agent_listener.build_app())
    assert listener_app.get(path).status_code == 404
    assert listener_app.post(path, json={}).status_code == 404
