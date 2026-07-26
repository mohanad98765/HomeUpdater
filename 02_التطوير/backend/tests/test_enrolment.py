"""Agent enrolment tokens — the one part of the agent spike whose correctness can
be proven now.

Everything here is about failing closed: an enrolment that succeeds on a bad token
hands a stranger an agent identity on a machine that runs as LOCAL SYSTEM.

Two of these tests exist because the module once CLAIMED a control it did not have:
``redeem`` never compared the caller's machine to the token, while the docstring and
the decision document both said an intercepted token could not be redeemed elsewhere.
Anything asserted in prose about this module now has a test under it.
"""

from __future__ import annotations

import base64
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services import enrolment


@pytest.fixture(autouse=True)
def _clean():
    enrolment.reset_for_tests()
    yield
    enrolment.reset_for_tests()


def test_minted_token_redeems_once():
    tok = enrolment.mint(target_hint="SRV-01", machine_id="machine-guid-1")
    result = enrolment.redeem(tok.token, machine_id="machine-guid-1")
    assert len(result["agent_fingerprint"]) == 32
    assert len(result["hub_public_key"]) == 64


def test_a_token_cannot_be_redeemed_twice():
    tok = enrolment.mint(machine_id="m1")
    enrolment.redeem(tok.token, machine_id="m1")
    with pytest.raises(enrolment.EnrolmentError, match="already_redeemed"):
        enrolment.redeem(tok.token, machine_id="m1")


def test_expired_token_is_refused():
    tok = enrolment.mint(machine_id="m1")
    # Re-sign the same payload with an expiry in the past, using the hub's own key,
    # so ONLY the expiry — not the signature — is what fails.
    key = enrolment._load_or_create_key()
    payload = json.loads(enrolment._b64d(tok.token.split(".")[1]))
    payload["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    stale = f"{enrolment.PREFIX}.{enrolment._b64(raw)}.{enrolment._b64(key.sign(raw))}"
    with pytest.raises(enrolment.EnrolmentError, match="expired"):
        enrolment.redeem(stale, machine_id="m1")


def test_token_signed_by_another_key_is_refused():
    """A token fabricated by anything other than this hub must not enrol."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = Ed25519PrivateKey.generate()
    payload = json.dumps(
        {
            "nonce": "abc",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "target_hint": "",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    forged = f"{enrolment.PREFIX}.{enrolment._b64(payload)}.{enrolment._b64(other.sign(payload))}"
    with pytest.raises(enrolment.EnrolmentError, match="bad_signature"):
        enrolment.redeem(forged, machine_id="m1")


def test_editing_the_expiry_breaks_the_signature():
    """Extending your own token's life must not be possible."""
    tok = enrolment.mint(machine_id="m1")
    prefix, payload_b64, sig = tok.token.split(".")
    payload = json.loads(enrolment._b64d(payload_b64))
    payload["expires_at"] = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    edited = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(enrolment.EnrolmentError, match="bad_signature"):
        enrolment.redeem(f"{prefix}.{enrolment._b64(edited)}.{sig}", machine_id="m1")


@pytest.mark.parametrize(
    "junk", ["", "   ", "nope", "HUENROL1.only-two", "OTHER.a.b", "HUENROL1.@@@.@@@"]
)
def test_garbage_never_enrols(junk):
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(junk, machine_id="m1")


def test_fingerprint_is_stable_and_not_reversible():
    a = enrolment.fingerprint("machine-guid-1")
    assert a == enrolment.fingerprint("machine-guid-1")
    assert a != enrolment.fingerprint("machine-guid-2")
    assert "machine-guid-1" not in a


def test_ttl_is_short():
    """A long-lived enrolment token is a standing credential in disguise."""
    assert enrolment.TOKEN_TTL_MINUTES <= 30
    tok = enrolment.mint(machine_id="m1")
    remaining = datetime.fromisoformat(tok.expires_at) - datetime.now(UTC)
    assert remaining <= timedelta(minutes=enrolment.TOKEN_TTL_MINUTES)


# --- the machine binding the module used to only claim ----------------------
def test_a_bound_token_is_refused_from_another_machine():
    """The test that was missing. A token that leaks — a screenshot, a ticket, a chat
    message — must be useless anywhere but the machine it was minted for."""
    tok = enrolment.mint(target_hint="SRV-01", machine_id="the-real-target")
    with pytest.raises(enrolment.EnrolmentError, match="wrong_machine"):
        enrolment.redeem(tok.token, machine_id="the-attackers-box")
    # …and the refusal must not have consumed the nonce: the real machine still enrols
    assert enrolment.redeem(tok.token, machine_id="the-real-target")["bound"] is True


def test_an_unbound_token_needs_an_explicit_decision():
    """Minting a token any machine can redeem is sometimes necessary, never accidental."""
    with pytest.raises(enrolment.EnrolmentError, match="allow_any_machine"):
        enrolment.mint(target_hint="unknown target")
    tok = enrolment.mint(target_hint="unknown target", allow_any_machine=True)
    result = enrolment.redeem(tok.token, machine_id="whoever-got-there-first")
    assert result["bound"] is False, "the caller must be told this agent is unverified"


def test_single_use_survives_a_hub_restart():
    """The redeemed-nonce store used to live in memory, so restarting the hub — which
    an attacker holding a token can wait for or cause — made the token usable again."""
    tok = enrolment.mint(machine_id="m1")
    enrolment.redeem(tok.token, machine_id="m1")
    importlib.reload(enrolment)  # a real process restart, not a helper that clears state
    with pytest.raises(enrolment.EnrolmentError, match="already_redeemed"):
        enrolment.redeem(tok.token, machine_id="m1")


def test_expired_nonces_do_not_accumulate_forever():
    """An expired token can never be redeemed, so its nonce need not be kept — that is
    what stops the store growing without bound on a busy hub."""
    tok = enrolment.mint(machine_id="m1")
    enrolment.redeem(tok.token, machine_id="m1")
    assert len(enrolment._load_redeemed()) == 1
    stale = {"dead-nonce": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    enrolment._save_redeemed({**enrolment._load_redeemed(), **stale})
    assert "dead-nonce" not in enrolment._load_redeemed()


def test_redemption_is_refused_when_it_cannot_be_recorded(monkeypatch):
    """Fail closed: granting an enrolment we cannot record makes single-use a fiction."""

    def boom(_entries):
        raise enrolment.EnrolmentError("nonce_store_unwritable: disk full")

    tok = enrolment.mint(machine_id="m1")
    monkeypatch.setattr(enrolment, "_save_redeemed", boom)
    with pytest.raises(enrolment.EnrolmentError, match="unwritable"):
        enrolment.redeem(tok.token, machine_id="m1")


def test_public_key_is_stable_across_calls():
    assert enrolment.public_key_hex() == enrolment.public_key_hex()


def test_b64_roundtrip_handles_padding():
    for n in range(1, 40):
        raw = bytes(range(n))
        assert enrolment._b64d(enrolment._b64(raw)) == raw


def test_token_carries_no_secret():
    """The payload is readable by design; it must not contain anything sensitive."""
    tok = enrolment.mint(target_hint="SRV-01", machine_id="machine-guid-1")
    payload = json.loads(base64.urlsafe_b64decode(tok.token.split(".")[1] + "=="))
    assert set(payload) == {"nonce", "expires_at", "target_hint", "target_fp"}
    # the binding is a truncated hash, so a readable payload still leaks nothing
    assert payload["target_fp"] == enrolment.fingerprint("machine-guid-1")
    assert "machine-guid-1" not in tok.token
