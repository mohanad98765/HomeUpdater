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
  * A token is bound AT MINT to the fingerprint of the machine it is for, and
    redemption from any other machine is refused.

    History, because the claim came before the code: until 2026-07-26 this module
    documented that binding as a fact while ``redeem`` never compared the caller's
    ``machine_id`` to anything — it hashed whatever it was handed. An adversarial
    review of the agent protocol caught it. A token that leaks (a screenshot, a
    ticket, a chat message) was therefore usable from any machine, and the project's
    own decision document listed the property under "proven". The binding is now
    real, an unbound token requires an explicit opt-in, and the negative test
    (right token, wrong machine) exists.
  * Redeemed nonces are persisted, so single-use survives a restart of the hub.
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


def mint(
    target_hint: str = "",
    *,
    machine_id: str | None = None,
    allow_any_machine: bool = False,
) -> EnrolmentToken:
    """Create a single-use enrolment token valid for a short window.

    ``machine_id`` binds the token to that machine: the fingerprint goes INSIDE the
    signed payload, and redemption from anywhere else is refused. Minting a token any
    machine can redeem is still possible — some targets are not known in advance —
    but it must be asked for with ``allow_any_machine=True`` so it is a decision, not
    an accident. The fingerprint is a truncated SHA-256, so carrying it in a readable
    payload discloses nothing about the machine.
    """
    if machine_id is None and not allow_any_machine:
        raise EnrolmentError("unbound_token_requires_allow_any_machine")
    key = _load_or_create_key()
    expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "expires_at": expires.isoformat(),
        "target_hint": target_hint,
        "target_fp": fingerprint(machine_id) if machine_id is not None else "",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = f"{PREFIX}.{_b64(raw)}.{_b64(key.sign(raw))}"
    return EnrolmentToken(token=token, expires_at=payload["expires_at"], nonce=payload["nonce"])


def _redeemed_file():
    return get_appdata_dir() / "enrolment_redeemed.json"


def _load_redeemed() -> dict[str, str]:
    """Redeemed nonce -> its expiry. Kept on disk: an in-memory set made "single use"
    a promise that a hub restart quietly broke, and the restart is exactly what an
    attacker who wants a second redemption would arrange."""
    file = _redeemed_file()
    if not file.exists():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        entries = data.get("redeemed", {}) if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        # Fail CLOSED: an unreadable store cannot prove a nonce is unused.
        raise EnrolmentError(f"nonce_store_unreadable: {exc}") from exc
    now = datetime.now(UTC)
    # Expired tokens can never be redeemed anyway, so their nonces need not be kept —
    # that is what stops this file growing forever.
    return {
        nonce: exp
        for nonce, exp in entries.items()
        if isinstance(exp, str) and _parse_iso(exp) and _parse_iso(exp) > now
    }


def _parse_iso(text: str):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _save_redeemed(entries: dict[str, str]) -> None:
    file = _redeemed_file()
    tmp = file.with_suffix(".tmp")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"redeemed": entries}, indent=1), encoding="utf-8")
        tmp.replace(file)  # atomic on Windows and POSIX
    except Exception as exc:  # noqa: BLE001
        # Fail CLOSED: if the redemption cannot be recorded, do not grant it.
        raise EnrolmentError(f"nonce_store_unwritable: {exc}") from exc


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
    redeemed = _load_redeemed()
    if not nonce or nonce in redeemed:
        raise EnrolmentError("already_redeemed")

    fp = fingerprint(machine_id)
    target_fp = payload.get("target_fp") or ""
    # The check this module claimed to perform for months and did not.
    if target_fp and target_fp != fp:
        logger.warning(
            f"enrolment refused: token bound to {target_fp[:12]}…, presented by {fp[:12]}…"
        )
        raise EnrolmentError("wrong_machine")

    redeemed[nonce] = payload["expires_at"]
    _save_redeemed(redeemed)  # raises rather than granting an unrecorded redemption
    logger.info(f"agent enrolled: fingerprint={fp[:12]}… bound={bool(target_fp)}")
    return {
        "agent_fingerprint": fp,
        "enrolled_at": datetime.now(UTC).isoformat(),
        "hub_public_key": public_key_hex(),
        # False means the token could have been redeemed by ANY machine. The caller
        # must treat such an agent as pending operator confirmation, never as trusted.
        "bound": bool(target_fp),
    }


def reset_for_tests() -> None:
    file = _redeemed_file()
    if file.exists():
        file.unlink()
