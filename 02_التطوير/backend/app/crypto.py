"""
At-rest encryption for stored secrets (SSH/WinRM passwords, Home Assistant token).

Secrets are encrypted with Fernet (AES-128-CBC + HMAC, from `cryptography`)
before they reach the SQLite DB and decrypted transparently on read via the
`EncryptedString` SQLAlchemy type in models/orm.py. This defeats the "copy the
DB file / read a cloud-synced backup and recover every credential" threat: the
DB file alone is useless without the key.

Key resolution (first that works wins):
  1. ``HOMEUPDATER_SECRET_KEY`` env var — a urlsafe-base64 Fernet key
     (deployment / CI / tests).
  2. ``settings.encryption_passphrase`` — a user passphrase; the Fernet key is
     derived with PBKDF2-HMAC-SHA256 over a per-install random salt.
  3. A random key persisted at ``<data_dir>/secret.key``. On Windows the key is
     wrapped with **DPAPI** (CryptProtectData) so it is bound to the Windows user
     account — copying it to another account/machine yields nothing usable.

Legacy plaintext rows (written before O.5) keep working: ``decrypt`` returns its
input unchanged when it is not a valid Fernet token, and the value is
re-encrypted on the next write.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from .config import get_data_dir

_KEY_FILE = "secret.key"
_SALT_FILE = "secret.salt"
_PBKDF2_ITERATIONS = 390_000


def _derive_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _dpapi_protect(data: bytes) -> bytes | None:
    try:
        import win32crypt

        return win32crypt.CryptProtectData(data, "HomeUpdater", None, None, None, 0)
    except Exception:
        return None


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    try:
        import win32crypt

        _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return data
    except Exception:
        return None


def _load_or_create_key() -> bytes:
    # 1) explicit env key (deployment / CI / tests)
    env_key = os.environ.get("HOMEUPDATER_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8") if isinstance(env_key, str) else env_key

    data_dir = get_data_dir()

    # 2) passphrase-derived (imported lazily so settings aren't built at import time)
    from .config import settings

    if settings.encryption_passphrase:
        salt_path = data_dir / _SALT_FILE
        if salt_path.exists():
            salt = salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            try:
                salt_path.write_bytes(salt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Could not persist key salt: {exc}")
        return _derive_from_passphrase(settings.encryption_passphrase, salt)

    # 3) persisted random key (DPAPI-wrapped on Windows)
    key_path = data_dir / _KEY_FILE
    if key_path.exists():
        raw = key_path.read_bytes()
        if os.name == "nt":
            unwrapped = _dpapi_unprotect(raw)
            if unwrapped is not None:
                return unwrapped
            # not DPAPI-wrapped (or a different user) — fall back to the raw bytes
        return raw

    key = Fernet.generate_key()
    to_store = key
    if os.name == "nt":
        protected = _dpapi_protect(key)
        if protected is not None:
            to_store = protected
    try:
        key_path.write_bytes(to_store)
        if os.name != "nt":
            os.chmod(key_path, 0o600)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not persist encryption key: {exc}")
    return key


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def reset_cache() -> None:
    """Drop the cached key/Fernet (used by tests that switch keys)."""
    _fernet.cache_clear()


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Empty/None pass through unchanged."""
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a stored secret; return the input unchanged if it is not a valid
    Fernet token (legacy plaintext written before at-rest encryption)."""
    if not token:
        return token
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return token
