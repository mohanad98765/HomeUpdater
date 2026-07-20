"""
App-level login gate — protects the UI/API behind a user password.

The app holds sensitive data (device inventory, encrypted SSH/WinRM/HA
credentials, the Anthropic key), so this adds a human-authentication layer on
top of the technical loopback protections (session-token + CSRF in main.py).

Design:
  - First run: no password exists -> the UI forces the user to CREATE one
    (there is deliberately NO default password — a fixed default like "admin"
    is the exact weak-credential class our own Security page warns about).
  - The password is stored only as a **PBKDF2-HMAC-SHA256 hash** (200k iters,
    per-password random salt) in ``<data_dir>/auth.json`` — never in plaintext.
  - On login the server issues a random in-memory **session token**; the UI
    sends it as ``X-HomeUpdater-Auth`` on every call. Sessions live in memory,
    so closing the app (server process) logs the user out — desired for a
    security tool.

Forgot the password? Delete ``%APPDATA%\\HomeUpdater\\data\\auth.json`` to reset
the lock (this only removes the gate; it is no weaker than the file access an
attacker on that account would already have).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from loguru import logger

from ..config import get_data_dir

_AUTH_FILE = "auth.json"
_ITERATIONS = 200_000
_MIN_LEN = 6

# Valid session tokens for this process run (cleared on restart).
_sessions: set[str] = set()


class AuthError(RuntimeError):
    """Raised on a bad password or a policy violation."""


def _auth_path():
    return get_data_dir() / _AUTH_FILE


def is_password_set() -> bool:
    return _auth_path().is_file()


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def set_password(password: str) -> None:
    """Create/replace the password (stored hashed). Enforces the length policy."""
    if not isinstance(password, str) or len(password) < _MIN_LEN:
        raise AuthError(f"كلمة المرور يجب أن تكون {_MIN_LEN} أحرف على الأقل.")
    salt = os.urandom(16)
    digest = _pbkdf2(password, salt, _ITERATIONS)
    record = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
        "iterations": _ITERATIONS,
    }
    path = _auth_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError as exc:  # disk full / read-only / AV lock — surface cleanly
        logger.error(f"Could not write auth.json: {exc}")
        raise AuthError(f"تعذّر حفظ كلمة المرور: {exc}") from exc
    logger.info("App password set/updated (hashed).")


def verify_password(password: str) -> bool:
    """Constant-time check of a candidate password against the stored hash."""
    if not is_password_set() or not isinstance(password, str):
        return False
    try:
        record = json.loads(_auth_path().read_text(encoding="utf-8"))
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        iterations = int(record.get("iterations", _ITERATIONS))
    except Exception as exc:  # noqa: BLE001 — corrupt file => deny, don't crash
        logger.error(f"auth.json unreadable: {exc}")
        return False
    return hmac.compare_digest(_pbkdf2(password, salt, iterations), expected)


def change_password(current: str, new: str) -> None:
    if not verify_password(current):
        raise AuthError("كلمة المرور الحالية غير صحيحة.")
    set_password(new)


# --- session tokens -------------------------------------------------------
def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    return token


def is_session_valid(token: str) -> bool:
    return bool(token) and token in _sessions


def revoke_session(token: str) -> None:
    _sessions.discard(token)


def revoke_all() -> None:
    _sessions.clear()
