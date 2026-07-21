"""Auth hardening (v1.4.4): login brute-force lockout and session expiry."""

from __future__ import annotations

from app.services import auth


def test_login_lockout_after_repeated_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_auth_path", lambda: tmp_path / "auth.json")
    auth._login_fails = 0
    auth._login_locked_until = 0.0
    auth.set_password("secret123")

    assert auth.login_locked_for() == 0
    for _ in range(auth._MAX_LOGIN_FAILS):
        assert not auth.verify_password("wrong-guess")
        auth.note_login_failure()
    assert auth.login_locked_for() > 0  # locked out after the threshold

    auth.note_login_success()  # a correct login clears it
    assert auth.login_locked_for() == 0


def test_session_absolute_and_idle_expiry(monkeypatch):
    token = auth.create_session()
    assert auth.is_session_valid(token)

    # Rewind its timestamps past the absolute expiry -> invalid + pruned.
    created, last = auth._sessions[token]
    old = auth._SESSION_ABSOLUTE_SECONDS + 1
    auth._sessions[token] = (created - old, last - old)
    assert not auth.is_session_valid(token)
    assert token not in auth._sessions


def test_session_cap_evicts_oldest(monkeypatch):
    auth.revoke_all()
    monkeypatch.setattr(auth, "_MAX_SESSIONS", 4)
    tokens = [auth.create_session() for _ in range(6)]
    assert len(auth._sessions) <= 4  # bounded
    assert auth.is_session_valid(tokens[-1])  # newest still valid
    auth.revoke_all()
