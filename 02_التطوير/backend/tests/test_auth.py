"""App password login gate — hashing, sessions, and the middleware gate.

The gate is opt-in: it activates only after a password is SET, so a fresh
install (and all other tests) behave exactly as before.
"""

from __future__ import annotations

import pytest

from app.services import auth

CSRF = {"X-HomeUpdater": "1"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Point auth.json at a temp dir and start each test with no sessions."""
    monkeypatch.setattr(auth, "get_data_dir", lambda: tmp_path)
    auth.revoke_all()
    yield
    auth.revoke_all()


# --- hashing / storage ---------------------------------------------------- #
def test_hash_roundtrip_and_never_plaintext(tmp_path):
    assert auth.is_password_set() is False
    auth.set_password("s3cret-pw")
    assert auth.is_password_set() is True
    assert auth.verify_password("s3cret-pw") is True
    assert auth.verify_password("wrong") is False
    on_disk = (tmp_path / "auth.json").read_text(encoding="utf-8")
    assert "s3cret-pw" not in on_disk  # only the salted hash is stored


def test_min_length_enforced():
    with pytest.raises(auth.AuthError):
        auth.set_password("123")  # shorter than the 6-char minimum


def test_change_requires_current_password():
    auth.set_password("first-pw")
    with pytest.raises(auth.AuthError):
        auth.change_password("bad", "second-pw")
    auth.change_password("first-pw", "second-pw")
    assert auth.verify_password("second-pw") is True
    assert auth.verify_password("first-pw") is False


def test_sessions_create_validate_revoke():
    t = auth.create_session()
    assert auth.is_session_valid(t) is True
    assert auth.is_session_valid("nope") is False
    assert auth.is_session_valid("") is False
    auth.revoke_session(t)
    assert auth.is_session_valid(t) is False


# --- the middleware gate, end-to-end -------------------------------------- #
def test_gate_is_opt_in_and_enforced_after_setup(client):
    # Fresh: no password -> gate OFF -> a protected route is reachable.
    assert client.get("/api/auth/status").json() == {"password_set": False}
    assert client.get("/api/system/info").status_code == 200

    # First-run setup creates the password + returns a session; gate turns ON.
    r = client.post("/api/auth/setup", json={"password": "hunter2!"}, headers=CSRF)
    assert r.status_code == 200
    token = r.json()["token"]
    assert client.get("/api/auth/status").json() == {"password_set": True}

    # setup cannot run a second time.
    assert (
        client.post("/api/auth/setup", json={"password": "other1"}, headers=CSRF).status_code == 409
    )

    # Protected route now needs the session token; blocked without it.
    assert client.get("/api/system/info", headers={"X-HomeUpdater-Auth": token}).status_code == 200
    assert client.get("/api/system/info").status_code == 401
    # Liveness stays exempt even when locked.
    assert client.get("/api/system/health").status_code == 200


def test_login_after_restart(client):
    client.post("/api/auth/setup", json={"password": "correct-horse"}, headers=CSRF)
    auth.revoke_all()  # simulate a fresh app launch (in-memory sessions cleared)

    assert client.get("/api/system/info").status_code == 401
    assert (
        client.post("/api/auth/login", json={"password": "WRONG"}, headers=CSRF).status_code == 401
    )
    r = client.post("/api/auth/login", json={"password": "correct-horse"}, headers=CSRF)
    assert r.status_code == 200
    token = r.json()["token"]
    assert client.get("/api/system/info", headers={"X-HomeUpdater-Auth": token}).status_code == 200


def test_check_endpoint_validates_session(client):
    # No password yet -> gate off -> /check reachable.
    assert client.get("/api/auth/check").status_code == 200
    token = client.post("/api/auth/setup", json={"password": "abc123"}, headers=CSRF).json()[
        "token"
    ]
    # Now gated: needs a valid session token.
    assert client.get("/api/auth/check").status_code == 401
    assert client.get("/api/auth/check", headers={"X-HomeUpdater-Auth": token}).status_code == 200
