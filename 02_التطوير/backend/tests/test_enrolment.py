"""Agent enrolment tokens — the one part of the agent spike whose correctness can
be proven now.

Everything here is about failing closed: an enrolment that succeeds on a bad token
hands a stranger an agent identity on a machine that runs as LOCAL SYSTEM. The
known gap (in-memory redeemed-nonce store) is asserted as a gap, not hidden.
"""

from __future__ import annotations

import base64
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
    tok = enrolment.mint(target_hint="SRV-01")
    result = enrolment.redeem(tok.token, machine_id="machine-guid-1")
    assert len(result["agent_fingerprint"]) == 32
    assert len(result["hub_public_key"]) == 64


def test_a_token_cannot_be_redeemed_twice():
    tok = enrolment.mint()
    enrolment.redeem(tok.token, machine_id="m1")
    with pytest.raises(enrolment.EnrolmentError, match="already_redeemed"):
        enrolment.redeem(tok.token, machine_id="m2")


def test_expired_token_is_refused():
    tok = enrolment.mint()
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
    tok = enrolment.mint()
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
    tok = enrolment.mint()
    remaining = datetime.fromisoformat(tok.expires_at) - datetime.now(UTC)
    assert remaining <= timedelta(minutes=enrolment.TOKEN_TTL_MINUTES)


def test_redeemed_store_is_documented_as_in_memory_only():
    """KNOWN GAP, asserted so it cannot be forgotten: the redeemed-nonce set does not
    survive a restart, so an unexpired token could be redeemed again. It must move to
    the database before the agent ships — see docs/AGENT_SPIKE.md risk #5."""
    tok = enrolment.mint()
    enrolment.redeem(tok.token, machine_id="m1")
    enrolment.reset_for_tests()  # stands in for a process restart
    enrolment.redeem(tok.token, machine_id="m-other")  # succeeds — that IS the gap


def test_public_key_is_stable_across_calls():
    assert enrolment.public_key_hex() == enrolment.public_key_hex()


def test_b64_roundtrip_handles_padding():
    for n in range(1, 40):
        raw = bytes(range(n))
        assert enrolment._b64d(enrolment._b64(raw)) == raw


def test_token_carries_no_secret():
    """The payload is readable by design; it must not contain anything sensitive."""
    tok = enrolment.mint(target_hint="SRV-01")
    payload = json.loads(base64.urlsafe_b64decode(tok.token.split(".")[1] + "=="))
    assert set(payload) == {"nonce", "expires_at", "target_hint"}
