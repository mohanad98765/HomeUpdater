"""Issue HomeUpdater license keys (vendor-side tool — never ship this).

The private key is the business asset: whoever holds it can mint keys. Keep it OUT
of the repository and off any machine a customer can reach; the app only ever needs
the public half, which is embedded in ``app/services/licensing.py``.

Generate a keypair once:
    python tools/make_license.py keygen --out C:\\keys\\homeupdater_license_key.pem
    # then paste the printed public hex into VENDOR_PUBLIC_KEY_HEX

Issue a key:
    python tools/make_license.py issue --key C:\\keys\\homeupdater_license_key.pem \\
        --licensee "عيادة النور" --tier evidence25 --months 12
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TIER_DEVICE_LIMIT = {"free": 0, "evidence25": 25, "evidence100": 100, "partner": 100000}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def keygen(out: Path) -> None:
    if out.exists():
        raise SystemExit(f"refusing to overwrite an existing key: {out}")
    priv = Ed25519PrivateKey.generate()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_hex = (
        priv.public_key()
        .public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        .hex()
    )
    print(f"private key written to: {out}")
    print("KEEP IT OUT OF THE REPO AND BACK IT UP — losing it means reissuing every key.")
    print(f'\nVENDOR_PUBLIC_KEY_HEX = "{pub_hex}"')


def issue(key_path: Path, licensee: str, tier: str, months: int, devices: int | None) -> None:
    if tier not in TIER_DEVICE_LIMIT:
        raise SystemExit(f"unknown tier {tier!r}; pick one of {sorted(TIER_DEVICE_LIMIT)}")
    priv = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    # UTC, to match both `issued_at` below and the checker in services/licensing.py.
    # Stamping a local date here made a key's real lifetime depend on the timezone it
    # was issued from: in Riyadh a key "valid until the 31st" died at 03:00 on the 1st.
    _today = datetime.now(UTC).date()
    expires = "" if months <= 0 else (_today + timedelta(days=30 * months)).isoformat()
    payload = {
        "licensee": licensee,
        "tier": tier,
        "devices_max": devices if devices is not None else TIER_DEVICE_LIMIT[tier],
        "expires": expires,
        "issued_at": datetime.now(UTC).date().isoformat(),
        "key_id": secrets.token_hex(6),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = priv.sign(raw)
    print(f"HU1.{_b64(raw)}.{_b64(sig)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("keygen")
    g.add_argument("--out", required=True, type=Path)

    i = sub.add_parser("issue")
    i.add_argument("--key", required=True, type=Path)
    i.add_argument("--licensee", required=True)
    i.add_argument("--tier", required=True)
    i.add_argument("--months", type=int, default=12, help="0 = perpetual")
    i.add_argument("--devices", type=int, default=None)

    args = ap.parse_args()
    if args.cmd == "keygen":
        keygen(args.out)
    else:
        issue(args.key, args.licensee, args.tier, args.months, args.devices)


if __name__ == "__main__":
    main()
