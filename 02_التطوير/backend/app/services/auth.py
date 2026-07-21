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
import time

from loguru import logger

from ..config import get_data_dir

_AUTH_FILE = "auth.json"
_ITERATIONS = 200_000
_MIN_LEN = 6

# Login brute-force throttle: after N consecutive failures, lock out briefly.
_MAX_LOGIN_FAILS = 5
_LOCKOUT_SECONDS = 30.0
_login_fails = 0
_login_locked_until = 0.0

# Session tokens: kept in memory (cleared on restart) with an idle + absolute
# expiry, so a captured/forgotten token can't stay valid for the whole (long,
# elevated) process lifetime. token -> (created, last_seen), monotonic seconds.
_SESSION_IDLE_SECONDS = 12 * 3600
_SESSION_ABSOLUTE_SECONDS = 24 * 3600
_MAX_SESSIONS = 32
_sessions: dict[str, tuple[float, float]] = {}


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


# --- login brute-force throttle -------------------------------------------
def login_locked_for() -> float:
    """Seconds remaining on the login lockout (0 if not locked)."""
    remaining = _login_locked_until - time.monotonic()
    return remaining if remaining > 0 else 0.0


def note_login_failure() -> None:
    global _login_fails, _login_locked_until
    _login_fails += 1
    if _login_fails >= _MAX_LOGIN_FAILS:
        _login_locked_until = time.monotonic() + _LOCKOUT_SECONDS
        _login_fails = 0


def note_login_success() -> None:
    global _login_fails, _login_locked_until
    _login_fails = 0
    _login_locked_until = 0.0


# --- session tokens -------------------------------------------------------
def _prune_sessions() -> None:
    now = time.monotonic()
    dead = [
        t
        for t, (created, last_seen) in _sessions.items()
        if now - created > _SESSION_ABSOLUTE_SECONDS or now - last_seen > _SESSION_IDLE_SECONDS
    ]
    for t in dead:
        _sessions.pop(t, None)


def create_session() -> str:
    _prune_sessions()
    if len(_sessions) >= _MAX_SESSIONS:  # drop the least-recently-seen session
        oldest = min(_sessions, key=lambda t: _sessions[t][1])
        _sessions.pop(oldest, None)
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    _sessions[token] = (now, now)
    return token


def is_session_valid(token: str) -> bool:
    if not token:
        return False
    rec = _sessions.get(token)
    if rec is None:
        return False
    created, _last_seen = rec
    now = time.monotonic()
    if now - created > _SESSION_ABSOLUTE_SECONDS or now - rec[1] > _SESSION_IDLE_SECONDS:
        _sessions.pop(token, None)
        return False
    _sessions[token] = (created, now)  # refresh the idle clock on use
    return True


def revoke_session(token: str) -> None:
    _sessions.pop(token, None)


def revoke_all() -> None:
    _sessions.clear()
