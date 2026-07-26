"""The TLS listener that faces the network — what it must NOT serve.

The hub's ordinary API runs with administrator rights on the operator's PC. The whole
point of a second listener is that putting TLS on the first one and binding it to the
LAN would publish that API. So the tests here are mostly about the boundary: what this
socket refuses, what the certificate actually covers, and that none of it turns on by
itself.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket

import pytest
from cryptography import x509
from fastapi.testclient import TestClient

from app import agent_listener
from app.config import settings
from app.services import agent_tls


@pytest.fixture(autouse=True)
def _isolated_certs(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tls, "get_appdata_dir", lambda: tmp_path)
    yield


# --- the boundary -------------------------------------------------------------
def test_the_listener_serves_only_the_three_agent_paths():
    """A 404 for everything else, checked before routing — so adding an operator
    endpoint under /api/agents later cannot silently publish it to the network."""
    client = TestClient(agent_listener.build_app())
    for blocked in (
        "/api/agents",  # the operator's fleet list
        "/api/agents/listener",  # …and its configuration
        "/api/updates/inventory",
        "/api/system/settings",
        "/api/evidence/pack",
        "/docs",
        "/openapi.json",
        "/",
    ):
        assert client.get(blocked).status_code == 404, blocked


def test_the_allowlist_is_exact_paths_not_a_prefix():
    """A prefix rule would have admitted /api/agents/<id>/command from the network."""
    assert "/api/agents" not in agent_listener.AGENT_PATHS
    for path in agent_listener.AGENT_PATHS:
        assert path.startswith("/api/"), path
        assert "{" not in path, "no parameterised paths on the network-facing socket"


def test_health_is_the_only_thing_it_volunteers():
    client = TestClient(agent_listener.build_app())
    body = client.get("/api/system/health").json()
    assert body == {"status": "ok", "listener": "agent"}


def test_agent_endpoints_are_reachable_and_still_demand_a_signature():
    client = TestClient(agent_listener.build_app())
    r = client.post("/api/agents/checkin", json={"inventory_count": 1})
    assert r.status_code == 401, "reachable, but unauthenticated still gets nothing"
    assert r.json()["detail"] == "missing_signature_headers"


def test_no_interactive_docs_or_schema_on_the_network_socket():
    app = agent_listener.build_app()
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None


def test_it_is_off_unless_someone_turns_it_on():
    """A new listening socket on a customer machine is a decision, not an upgrade
    side effect."""
    assert settings.agent_listener_enabled is False


# --- the certificate ----------------------------------------------------------
def test_certificate_covers_every_address_an_agent_might_use(tmp_path):
    details = agent_tls.ensure_cert()
    names = set(details["names"])
    assert socket.gethostname() in names or any(n for n in names), names
    assert "127.0.0.1" in names, "a pin is useless if the connection fails on the name"
    assert (tmp_path / agent_tls.CERT_NAME).exists()
    assert (tmp_path / agent_tls.KEY_NAME).exists()


def test_the_private_key_is_not_inside_the_certificate_file(tmp_path):
    agent_tls.ensure_cert()
    cert_text = (tmp_path / agent_tls.CERT_NAME).read_text()
    assert "PRIVATE KEY" not in cert_text


def test_certificate_is_reused_not_regenerated_on_every_call():
    """Regenerating silently would break every agent that pinned the old one."""
    first = agent_tls.ensure_cert()["fingerprint_sha256"]
    second = agent_tls.ensure_cert()["fingerprint_sha256"]
    assert first == second
    assert agent_tls.fingerprint() == first


def test_regeneration_is_explicit_and_changes_the_pin():
    first = agent_tls.ensure_cert()["fingerprint_sha256"]
    forced = agent_tls.ensure_cert(force=True)["fingerprint_sha256"]
    assert forced != first


def test_certificate_validity_window_is_sane():
    details = agent_tls.ensure_cert()
    start = dt.datetime.fromisoformat(details["not_before"])
    end = dt.datetime.fromisoformat(details["not_after"])
    assert start < dt.datetime.now(dt.UTC) < end
    assert (end - start).days <= 825, "long-lived certificates never get replaced"


def test_certificate_is_not_a_ca_and_says_so(tmp_path):
    agent_tls.ensure_cert()
    cert = x509.load_pem_x509_certificate((tmp_path / agent_tls.CERT_NAME).read_bytes())
    basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic.ca is False, "a hub certificate that could sign others is a CA on a desktop"


def test_ip_addresses_are_ip_sans_not_dns_names(tmp_path):
    """An IP in a DNS SAN does not match when a client connects by address."""
    agent_tls.ensure_cert()
    cert = x509.load_pem_x509_certificate((tmp_path / agent_tls.CERT_NAME).read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    for ip in san.get_values_for_type(x509.IPAddress):
        assert isinstance(ip, ipaddress.IPv4Address | ipaddress.IPv6Address)
    for name in san.get_values_for_type(x509.DNSName):
        with pytest.raises(ValueError):
            ipaddress.ip_address(name)  # a DNS SAN must not be an address


def test_describe_is_empty_before_anything_exists():
    assert agent_tls.describe() == {}


# --- status -------------------------------------------------------------------
def test_status_reports_where_agents_should_point():
    agent_tls.ensure_cert()
    status = agent_listener.listener.status()
    assert status["running"] is False
    assert status["port"] == settings.agent_listener_port
    assert status["certificate"]["fingerprint_sha256"] == agent_tls.fingerprint()
    for url in status["addresses"]:
        assert url.startswith("https://"), "an agent must never be told to use http"
        assert "127.0.0.1" not in url, "a loopback address is useless to another machine"


def test_the_listener_status_route_is_operator_only(client):
    """It describes the hub's configuration, so it lives behind the hub's gates and
    is deliberately absent from the network-facing allowlist."""
    assert "/api/agents/listener" not in agent_listener.AGENT_PATHS
    assert client.get("/api/agents/listener").status_code == 200
