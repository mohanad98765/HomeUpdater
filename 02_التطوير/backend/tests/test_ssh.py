"""Tests for the SSH/Linux integration (SSH itself is monkeypatched)."""

from __future__ import annotations

from app.services import ssh
from tests.conftest import CSRF_HEADER

OS_RELEASE = """NAME="Ubuntu"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 22.04.3 LTS"
VERSION_ID="22.04"
"""

APT = """Listing...
nginx/jammy-updates 1.18.0-6ubuntu14.4 amd64 [upgradable from: 1.18.0-6ubuntu14.3]
openssl/jammy-security 3.0.2-0ubuntu1.12 amd64 [upgradable from: 3.0.2-0ubuntu1.10]
"""

DNF = """Last metadata expiration check: 0:10:00 ago.
httpd.x86_64  2.4.57-5.fc39  updates
kernel.x86_64  6.6.8-200.fc39  updates
"""


def test_parse_os_release():
    kv = ssh.parse_os_release(OS_RELEASE)
    assert kv["ID"] == "ubuntu"
    assert kv["PRETTY_NAME"] == "Ubuntu 22.04.3 LTS"


def test_pkg_manager_for():
    assert ssh.pkg_manager_for("ubuntu", "debian") == "apt"
    assert ssh.pkg_manager_for("fedora", "") == "dnf"
    assert ssh.pkg_manager_for("arch", "") == ""


def test_parse_apt_upgradable():
    pkgs = ssh.parse_apt_upgradable(APT)
    assert len(pkgs) == 2
    assert pkgs[0]["name"] == "nginx"
    assert pkgs[0]["available"] == "1.18.0-6ubuntu14.4"
    assert pkgs[0]["current"] == "1.18.0-6ubuntu14.3"


def test_parse_dnf_updates():
    pkgs = ssh.parse_dnf_updates(DNF)
    assert len(pkgs) == 2
    assert pkgs[0]["name"] == "httpd.x86_64"
    assert pkgs[0]["available"] == "2.4.57-5.fc39"


def test_add_host_verifies_and_hides_password(client, monkeypatch):
    async def fake_probe(host, port, username, password, known_host_key=None):
        return {
            "os_name": "Ubuntu 22.04",
            "os_id": "ubuntu",
            "pkg_manager": "apt",
            "host_key": "ssh-ed25519 AAAATESTKEY",
        }

    monkeypatch.setattr(ssh, "probe", fake_probe)
    r = client.post(
        "/api/ssh/hosts",
        json={"host": "10.0.0.9", "username": "pi", "password": "secret"},
        headers=CSRF_HEADER,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pkg_manager"] == "apt"
    assert body["has_password"] is True
    assert body["host_key_verified"] is True  # TOFU captured the key
    assert "password" not in body
    assert "host_key" not in body  # the key line itself is not exposed
    assert client.get("/api/ssh/hosts").json()["total"] == 1


def test_add_host_rejects_bad_connection(client, monkeypatch):
    async def bad_probe(host, port, username, password, known_host_key=None):
        raise ssh.SSHError("Authentication failed")

    monkeypatch.setattr(ssh, "probe", bad_probe)
    r = client.post(
        "/api/ssh/hosts",
        json={"host": "10.0.0.9", "username": "pi", "password": "bad"},
        headers=CSRF_HEADER,
    )
    assert r.status_code == 400


def test_check_updates(client, monkeypatch):
    async def fake_probe(host, port, username, password, known_host_key=None):
        return {"os_name": "Ubuntu", "os_id": "ubuntu", "pkg_manager": "apt", "host_key": "k"}

    async def fake_check(host, port, username, password, pkg_manager, known_host_key=None):
        return {"total": 2, "packages": [{"name": "nginx", "current": "1", "available": "2"}]}

    monkeypatch.setattr(ssh, "probe", fake_probe)
    monkeypatch.setattr(ssh, "check_updates", fake_check)
    add = client.post(
        "/api/ssh/hosts",
        json={"host": "10.0.0.9", "username": "pi", "password": "x"},
        headers=CSRF_HEADER,
    ).json()
    r = client.post(f"/api/ssh/hosts/{add['id']}/check", json={}, headers=CSRF_HEADER)
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_check_verifies_against_stored_host_key(client, monkeypatch):
    """The stored TOFU host key is passed to check_updates for verification."""
    seen = {}

    async def fake_probe(host, port, username, password, known_host_key=None):
        return {"os_name": "Ubuntu", "os_id": "ubuntu", "pkg_manager": "apt", "host_key": "KEY-1"}

    async def fake_check(host, port, username, password, pkg_manager, known_host_key=None):
        seen["key"] = known_host_key
        return {"total": 0, "packages": []}

    monkeypatch.setattr(ssh, "probe", fake_probe)
    monkeypatch.setattr(ssh, "check_updates", fake_check)
    add = client.post(
        "/api/ssh/hosts",
        json={"host": "10.0.0.9", "username": "pi", "password": "x"},
        headers=CSRF_HEADER,
    ).json()
    client.post(f"/api/ssh/hosts/{add['id']}/check", json={}, headers=CSRF_HEADER)
    assert seen["key"] == "KEY-1"  # the captured key is used to verify later connects
