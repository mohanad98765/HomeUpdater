"""The agent endpoints — every test here is an attack that must fail.

The agent runs as LOCAL SYSTEM on a customer machine, so the failure this suite is
written against is not "a bug": it is a stranger obtaining, keeping, or reusing the
ability to make that service act. Each test corresponds to a finding that survived
the adversarial review of the protocol (03_الوثائق/AGENT_PROTOCOL.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import agent_auth, enrolment

CSRF = {"X-HomeUpdater": "1"}


@pytest.fixture(autouse=True)
def _clean_enrolment():
    enrolment.reset_for_tests()
    yield
    enrolment.reset_for_tests()


class Agent:
    """A test double for the real agent: holds a key, signs requests properly."""

    def __init__(self, client, machine_id="machine-1", name="SRV-01"):
        self.client = client
        self.machine_id = machine_id
        self.key = Ed25519PrivateKey.generate()
        self.public_hex = self.key.public_key().public_bytes_raw().hex()
        self.name = name
        self.id: str | None = None

    def enrol(self, *, bound=True, token=None):
        tok = (
            token
            or enrolment.mint(
                target_hint=self.name,
                machine_id=self.machine_id if bound else None,
                allow_any_machine=not bound,
            ).token
        )
        r = self.client.post(
            "/api/agents/enrol",
            json={
                "token": tok,
                "machine_id": self.machine_id,
                "public_key": self.public_hex,
                "name": self.name,
                "os_name": "Windows 11",
                "agent_version": "1.0.0",
            },
        )
        if r.status_code == 200:
            self.id = r.json()["agent_id"]
        return r

    def headers(self, method, path, body: bytes, *, timestamp=None, nonce=None, agent_id=None):
        agent_id = agent_id or self.id or ""
        timestamp = timestamp or datetime.now(UTC).isoformat()
        nonce = nonce or secrets.token_hex(16)
        sig = self.key.sign(
            agent_auth.signing_input(agent_id, method, path, timestamp, nonce, body)
        )
        return {
            "X-HU-Agent": agent_id,
            "X-HU-Timestamp": timestamp,
            "X-HU-Nonce": nonce,
            "X-HU-Signature": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    def post(self, path, payload: dict, **kw):
        body = json.dumps(payload).encode()
        return self.client.post(path, content=body, headers=self.headers("POST", path, body, **kw))

    def checkin(self, **kw):
        return self.post(
            "/api/agents/checkin",
            {"agent_version": "1.0.0", "inventory_count": 42, "pending_updates": 3},
            **kw,
        )


# --- enrolment ---------------------------------------------------------------
def test_a_bound_enrolment_creates_an_active_agent(client):
    a = Agent(client)
    r = a.enrol()
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["requires_confirmation"] is False
    assert len(body["agent_id"]) == 36


def test_an_unbound_enrolment_creates_a_PENDING_agent(client):
    """A token any machine could redeem must not produce a trusted agent."""
    a = Agent(client)
    r = a.enrol(bound=False)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["requires_confirmation"] is True


def test_a_pending_agent_receives_no_commands(client):
    """Otherwise the confirmation step is decorative."""
    a = Agent(client)
    a.enrol(bound=False)
    r = a.checkin()
    assert r.status_code == 200
    assert r.json()["commands"] == []


def test_enrolment_from_the_wrong_machine_is_refused(client):
    tok = enrolment.mint(machine_id="the-real-target").token
    thief = Agent(client, machine_id="the-attackers-box")
    r = thief.enrol(token=tok)
    assert r.status_code == 401
    assert "wrong_machine" in r.json()["detail"]


def test_a_token_cannot_enrol_twice(client):
    tok = enrolment.mint(machine_id="machine-1").token
    assert Agent(client).enrol(token=tok).status_code == 200
    second = Agent(client, machine_id="machine-1")
    assert second.enrol(token=tok).status_code == 401


def test_a_revoked_agent_cannot_re_enrol_itself(client):
    """Re-enrolment is how a reinstalled agent keeps its history — it must not be a
    way for a revoked machine to come back on its own."""
    a = Agent(client)
    a.enrol()
    assert client.post(f"/api/agents/{a.id}/revoke", headers=CSRF).status_code == 200
    fresh = Agent(client, machine_id=a.machine_id)
    assert fresh.enrol().status_code == 403


# --- the signature -----------------------------------------------------------
def test_checkin_requires_a_signature(client):
    a = Agent(client)
    a.enrol()
    r = client.post("/api/agents/checkin", json={"inventory_count": 1})
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_signature_headers"


def test_a_signature_from_another_key_is_refused(client):
    a = Agent(client)
    a.enrol()
    a.key = Ed25519PrivateKey.generate()  # same agent id, different key
    r = a.checkin()
    assert r.status_code == 401 and r.json()["detail"] == "bad_signature"


def test_a_signature_is_not_reusable_on_another_endpoint(client):
    """The path is inside the signed input, so a captured check-in cannot be replayed
    against /result."""
    a = Agent(client)
    a.enrol()
    body = json.dumps({"command_id": 1, "ok": True}).encode()
    headers = a.headers("POST", "/api/agents/checkin", body)  # signed for the WRONG path
    r = client.post("/api/agents/result", content=body, headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "bad_signature"


def test_a_replayed_request_is_refused(client):
    a = Agent(client)
    a.enrol()
    body = json.dumps({"agent_version": "1.0.0", "inventory_count": 1}).encode()
    headers = a.headers("POST", "/api/agents/checkin", body)
    assert client.post("/api/agents/checkin", content=body, headers=headers).status_code == 200
    again = client.post("/api/agents/checkin", content=body, headers=headers)
    assert again.status_code == 401 and again.json()["detail"] == "replayed_nonce"


def test_a_stale_timestamp_is_refused_and_the_skew_is_named(client):
    """Told, not silent: an agent whose clock drifts must learn why it was refused."""
    a = Agent(client)
    a.enrol()
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    r = a.checkin(timestamp=old)
    assert r.status_code == 401
    assert r.json()["detail"].startswith("clock_skew:")


def test_an_unknown_agent_id_is_refused(client):
    a = Agent(client)
    a.enrol()
    r = a.checkin(agent_id="00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401 and r.json()["detail"] == "unknown_agent"


def test_the_agent_id_is_inside_the_signature(client):
    """Revocation kills an id, not a key: if the id were merely an unsigned header, a
    captured signature would keep working under a newly enrolled id of the same key."""
    a = Agent(client)
    a.enrol()
    b = Agent(client, machine_id="machine-2", name="SRV-02")
    b.key = a.key  # same key material, different identity
    b.enrol()
    body = json.dumps({"inventory_count": 1}).encode()
    headers = a.headers("POST", "/api/agents/checkin", body)  # signed as agent A
    headers["X-HU-Agent"] = b.id  # …presented as agent B
    r = client.post("/api/agents/checkin", content=body, headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "bad_signature"


def test_a_revoked_agent_is_refused_on_its_next_request(client):
    a = Agent(client)
    a.enrol()
    assert a.checkin().status_code == 200
    client.post(f"/api/agents/{a.id}/revoke", headers=CSRF)
    r = a.checkin()
    assert r.status_code == 403 and r.json()["detail"] == "revoked"


def test_an_oversized_body_is_refused_before_it_is_parsed(client):
    """The cost of a huge 'inventory' must not be paid on behalf of an unverified
    caller — size is checked before the signature, let alone the JSON."""
    a = Agent(client)
    a.enrol()
    huge = json.dumps({"agent_version": "x" * (agent_auth.MAX_BODY_BYTES + 100)}).encode()
    r = client.post(
        "/api/agents/checkin",
        content=huge,
        headers=a.headers("POST", "/api/agents/checkin", huge),
    )
    assert r.status_code == 413 and r.json()["detail"] == "body_too_large"


# --- commands ----------------------------------------------------------------
def test_a_queued_command_reaches_the_agent_once(client):
    a = Agent(client)
    a.enrol()
    r = client.post(
        f"/api/agents/{a.id}/command",
        json={"kind": "windows_updates_install", "update_ids": ["KB5000001"]},
        headers=CSRF,
    )
    assert r.status_code == 200
    first = a.checkin().json()["commands"]
    assert len(first) == 1 and first[0]["kind"] == "windows_updates_install"
    assert first[0]["update_ids"] == ["KB5000001"]
    # …and not a second time: it is marked sent when handed over
    assert a.checkin().json()["commands"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "run_shell", "update_ids": ["whoami"]},  # there is no such kind
        {"kind": "", "update_ids": ["x"]},
        {"kind": "windows_updates_install"},  # required ids missing
        {"kind": "windows_updates_install", "update_ids": []},
        {"kind": "software_upgrade"},
    ],
)
def test_unknown_or_incomplete_commands_are_refused(client, payload):
    a = Agent(client)
    a.enrol()
    r = client.post(f"/api/agents/{a.id}/command", json=payload, headers=CSRF)
    assert r.status_code == 400


def test_a_command_cannot_be_queued_for_a_pending_agent(client):
    a = Agent(client)
    a.enrol(bound=False)
    r = client.post(f"/api/agents/{a.id}/command", json={"kind": "inventory"}, headers=CSRF)
    assert r.status_code == 409 and r.json()["detail"] == "agent_pending"


def test_an_agent_cannot_close_another_agents_command(client):
    """Confused deputy: without the ownership check, any agent could report the
    outcome of work issued to a different machine."""
    a = Agent(client)
    a.enrol()
    b = Agent(client, machine_id="machine-2", name="SRV-02")
    b.enrol()
    cmd = client.post(
        f"/api/agents/{a.id}/command", json={"kind": "inventory"}, headers=CSRF
    ).json()
    r = b.post("/api/agents/result", {"command_id": cmd["id"], "ok": True, "summary": "done"})
    assert r.status_code == 404 and r.json()["detail"] == "command_not_found"


def test_a_result_closes_the_command_and_is_audited(client):
    a = Agent(client)
    a.enrol()
    cmd = client.post(
        f"/api/agents/{a.id}/command", json={"kind": "inventory"}, headers=CSRF
    ).json()
    a.checkin()
    r = a.post(
        "/api/agents/result",
        {"command_id": cmd["id"], "ok": True, "summary": "115 products", "reboot_required": False},
    )
    assert r.status_code == 200
    listed = client.get(f"/api/agents/{a.id}/commands").json()["commands"]
    assert listed[0]["status"] == "done" and listed[0]["result"] == "115 products"
    kinds = [e["kind"] for e in client.get("/api/audit/events?limit=50").json()["events"]]
    for expected in (
        "agent_enrol",
        "agent_command_issued",
        "agent_checkin",
        "agent_command_result",
    ):
        assert expected in kinds, expected


def test_checkin_is_audited_as_a_summary_not_a_full_inventory(client):
    """verify() reads the whole chain, so a fleet writing its inventory into the log
    every minute would make the audit trail unverifiable in practice."""
    a = Agent(client)
    a.enrol()
    a.checkin()
    entry = next(
        e
        for e in client.get("/api/audit/events?limit=20").json()["events"]
        if e["kind"] == "agent_checkin"
    )
    detail = entry["detail"] if isinstance(entry["detail"], dict) else json.loads(entry["detail"])
    assert set(detail) == {"agent_id", "inventory", "pending_updates", "commands"}
    assert detail["inventory"] == 42


def test_confirming_a_pending_agent_lets_it_receive_work(client):
    a = Agent(client)
    a.enrol(bound=False)
    assert client.post(f"/api/agents/{a.id}/confirm", headers=CSRF).status_code == 200
    client.post(f"/api/agents/{a.id}/command", json={"kind": "inventory"}, headers=CSRF)
    assert len(a.checkin().json()["commands"]) == 1


def test_the_agent_list_never_exposes_the_public_key(client):
    """Not a secret, but the operator compares FINGERPRINTS on the target machine —
    showing a key invites comparing the wrong thing."""
    a = Agent(client)
    a.enrol()
    row = client.get("/api/agents").json()["agents"][0]
    assert "public_key" not in row
    assert row["fingerprint"] == enrolment.fingerprint(a.machine_id)


def test_signing_input_is_exactly_the_documented_shape():
    """Changing this breaks every deployed agent, so it is pinned by a test."""
    body = b'{"a":1}'
    got = agent_auth.signing_input("aid", "post", "/api/agents/checkin", "TS", "N", body)
    assert (
        got
        == b"aid\nPOST\n/api/agents/checkin\nTS\nN\n" + hashlib.sha256(body).hexdigest().encode()
    )
