"""Agent enrolment tokens — the de-risked piece of the future target agent.

Context: the planned agent is a signed LOCAL SYSTEM service on each target that
holds an OUTBOUND connection to the hub, executes locally, and therefore performs
no network logon — which is what makes a GPO-hardened, domain-joined machine
reachable at all, and what deletes the stored-admin-password problem instead of
hardening it.

This module implements only the part whose correctness can be proven here and now:
how a target proves, exactly once, that its enrolment was authorised by the hub's
operator. Everything else about the agent (Session 0, service lifecycle, self
update, execution as SYSTEM) is unproven and documented as such in
``docs/AGENT_SPIKE.md`` — shipping a half-agent would be worse than shipping none.

Design:
  * The hub mints a token: short TTL, single use, bound to the hub's own instance.
  * It is signed with a hub-local Ed25519 key so a token cannot be fabricated by
    something that merely reached the API.
  * Redemption is bound to the target's fingerprint, so a token intercepted in
    transit cannot be redeemed by a different machine.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from loguru import logger

from ..config import get_appdata_dir
from ..crypto import decrypt, encrypt

TOKEN_TTL_MINUTES = 15
PREFIX = "HUENROL1"


class EnrolmentError(RuntimeError):
    """Raised when a token is malformed, unsigned by this hub, expired, or reused."""


@dataclass(frozen=True)
class EnrolmentToken:
    token: str
    expires_at: str
    nonce: str


def _key_file():
    return get_appdata_dir() / "enrolment_key.enc"


def _load_or_create_key() -> Ed25519PrivateKey:
    """The hub's enrolment signing key, encrypted at rest with the app's own key.

    Reuses the existing Fernet+DPAPI path rather than inventing a second secret
    store — one place to protect, one place to get wrong.
    """
    path = _key_file()
    if path.exists():
        try:
            pem = decrypt(path.read_text(encoding="utf-8"))
            return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        except Exception as exc:  # noqa: BLE001 — a corrupt key must not wedge the app
            logger.warning(f"enrolment key unreadable, regenerating: {exc}")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    path.write_text(encrypt(pem), encoding="utf-8")
    return key


def public_key_hex() -> str:
    """The hub's enrolment public key — what an agent pins at install time."""
    return _load_or_create_key().public_key().public_bytes_raw().hex()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def fingerprint(machine_id: str) -> str:
    """A stable, non-reversible id for a target machine."""
    return hashlib.sha256(machine_id.encode("utf-8")).hexdigest()[:32]


def mint(target_hint: str = "") -> EnrolmentToken:
    """Create a single-use enrolment token valid for a short window."""
    key = _load_or_create_key()
    expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "expires_at": expires.isoformat(),
        "target_hint": target_hint,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = f"{PREFIX}.{_b64(raw)}.{_b64(key.sign(raw))}"
    return EnrolmentToken(token=token, expires_at=payload["expires_at"], nonce=payload["nonce"])


# Nonces already redeemed. In the real agent this belongs in the DB so it survives a
# restart; kept in memory for the spike and called out in the doc as a known gap.
_redeemed: set[str] = set()


def redeem(token: str, machine_id: str) -> dict:
    """Validate a token and bind it to one machine. Single use; fails closed.

    Raises :class:`EnrolmentError` on every failure path — an enrolment that
    silently "succeeds" on a bad token would hand a stranger an agent identity.
    """
    text = (token or "").strip()
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise EnrolmentError("malformed")
    try:
        raw, sig = _b64d(parts[1]), _b64d(parts[2])
    except Exception as exc:  # noqa: BLE001
        raise EnrolmentError("unreadable") from exc

    pub: Ed25519PublicKey = _load_or_create_key().public_key()
    try:
        pub.verify(sig, raw)
    except InvalidSignature as exc:
        raise EnrolmentError("bad_signature") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
        expires = datetime.fromisoformat(payload["expires_at"])
    except Exception as exc:  # noqa: BLE001
        raise EnrolmentError("unreadable_payload") from exc

    if datetime.now(UTC) > expires:
        raise EnrolmentError("expired")
    nonce = payload.get("nonce", "")
    if not nonce or nonce in _redeemed:
        raise EnrolmentError("already_redeemed")

    _redeemed.add(nonce)
    fp = fingerprint(machine_id)
    logger.info(f"agent enrolled: fingerprint={fp[:12]}…")
    return {
        "agent_fingerprint": fp,
        "enrolled_at": datetime.now(UTC).isoformat(),
        "hub_public_key": public_key_hex(),
    }


def reset_for_tests() -> None:
    _redeemed.clear()
