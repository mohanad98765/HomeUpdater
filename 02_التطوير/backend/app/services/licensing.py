"""Offline license keys — Ed25519 signed, verified with an embedded PUBLIC key.

Design choice that matters: the app ships only the **public** key, so a key can be
verified offline but cannot be minted without the private key, which never leaves
the vendor's machine. An HMAC scheme would have put the minting secret inside the
binary, where anyone can read it.

Honest limits, stated here so nobody oversells this:
  * Any client-side check can be bypassed by patching the binary. This stops casual
    key sharing and makes forging a key infeasible; it is not DRM and does not
    pretend to be.
  * There is no phone-home and no activation server — deliberate, because the
    product's whole pitch is that nothing leaves the customer's network. The cost
    is that a leaked key stays usable until it expires.

A key is a compact string: ``HU1.<base64url(payload_json)>.<base64url(signature)>``
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger

from ..config import get_appdata_dir

PREFIX = "HU1"

# The vendor's public key (hex). Replace via tools/make_license.py when rotating.
# Only the PRIVATE half can issue keys, and it is not in this repository.
VENDOR_PUBLIC_KEY_HEX = "8bd7474300dc781fa8f879830a1f8c7069f249976bc8f33abd6c8e853a476cce"

TIERS = ("free", "evidence25", "evidence100", "partner")
# Device ceilings per tier. "free" gets the whole app but no stamped evidence pack.
TIER_DEVICE_LIMIT = {"free": 0, "evidence25": 25, "evidence100": 100, "partner": 100000}


class LicenseError(RuntimeError):
    """Raised when a key is malformed, unsigned by us, expired, or unknown-tier."""


@dataclass
class License:
    """A verified license. ``valid`` is only ever True after signature checking."""

    tier: str = "free"
    licensee: str = ""
    devices_max: int = 0
    expires: str = ""  # ISO date, "" = perpetual
    issued_at: str = ""
    key_id: str = ""
    valid: bool = False
    reason: str = ""
    raw: str = field(default="", repr=False)

    @property
    def expired(self) -> bool:
        if not self.expires:
            return False
        try:
            return date.fromisoformat(self.expires) < datetime.now(UTC).date()
        except ValueError:
            return True  # an unparseable expiry is treated as expired, not as perpetual

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "licensee": self.licensee,
            "devices_max": self.devices_max,
            "expires": self.expires,
            "issued_at": self.issued_at,
            "key_id": self.key_id,
            "valid": self.valid and not self.expired,
            "expired": self.expired,
            "reason": self.reason,
            # What the license actually unlocks, so the UI never has to guess.
            "can_export_evidence": self.valid and not self.expired and self.tier != "free",
        }


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _public_key() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(VENDOR_PUBLIC_KEY_HEX))


def parse(key: str) -> License:
    """Verify a key's signature and shape. Never raises — returns an invalid License.

    Failing closed matters here: any error path must land on ``valid=False``, not on
    an exception a caller might swallow into "assume licensed".
    """
    text = (key or "").strip().replace("\n", "").replace(" ", "")
    if not text:
        return License(reason="empty")
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        return License(reason="malformed", raw=text)
    try:
        payload_b, sig = _b64d(parts[1]), _b64d(parts[2])
        _public_key().verify(sig, payload_b)  # signature over the RAW payload bytes
    except InvalidSignature:
        return License(reason="bad_signature", raw=text)
    except Exception as exc:  # noqa: BLE001 — malformed base64/hex etc.
        return License(reason=f"unreadable: {exc}", raw=text)

    try:
        data = json.loads(payload_b.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return License(reason="unreadable_payload", raw=text)

    tier = str(data.get("tier", "")).strip()
    if tier not in TIERS:
        return License(reason=f"unknown_tier:{tier}", raw=text)

    lic = License(
        tier=tier,
        licensee=str(data.get("licensee", "")),
        devices_max=int(data.get("devices_max", TIER_DEVICE_LIMIT.get(tier, 0))),
        expires=str(data.get("expires", "")),
        issued_at=str(data.get("issued_at", "")),
        key_id=str(data.get("key_id", "")),
        valid=True,
        raw=text,
    )
    if lic.expired:
        lic.reason = "expired"
    return lic


# --- storage ---------------------------------------------------------------
def _key_path():
    return get_appdata_dir() / "license.key"


def save(key: str) -> License:
    """Verify first, then persist. An invalid key is never written."""
    lic = parse(key)
    if not lic.valid:
        raise LicenseError(lic.reason or "invalid")
    try:
        _key_path().write_text(lic.raw, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise LicenseError(f"could not store the key: {exc}") from exc
    logger.info(f"license activated: tier={lic.tier} licensee={lic.licensee!r}")
    return lic


def load() -> License:
    """The stored license, re-verified on every read (never trusted from disk)."""
    path = _key_path()
    if not path.exists():
        return License(reason="none")
    try:
        return parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"could not read the license file: {exc}")
        return License(reason="unreadable_file")


def clear() -> None:
    path = _key_path()
    if path.exists():
        path.unlink()


def require_evidence_export() -> License:
    """Gate for the stamped evidence pack. Raises with a precise reason."""
    lic = load()
    d = lic.to_dict()
    if not d["can_export_evidence"]:
        raise LicenseError(d["reason"] or ("expired" if d["expired"] else "not_licensed"))
    return lic
