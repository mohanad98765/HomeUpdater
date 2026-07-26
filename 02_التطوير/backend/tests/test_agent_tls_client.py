"""The agent against a REAL TLS listener — the path every other test skipped.

Every existing agent test drives the hub through a loopback http TestClient, which is
what let a shipped defect through: the agent computed the certificate fingerprint,
compared it, and then opened an ordinary httpx client. An ordinary client verifies
against the system trust store, so it rejected the hub's self-signed certificate with
CERTIFICATE_VERIFY_FAILED *before* the pin was ever consulted — the agent could not
reach a TLS hub at all. Found by running it for real, not by reading it.

So these tests start an actual TLS server with an actual generated certificate and make
the agent talk to it over a socket.
"""

from __future__ import annotations

import http.server
import ssl
import threading

import httpx
import pytest

from app import agent_mode
from app.services import agent_tls


@pytest.fixture
def tls_server(tmp_path, monkeypatch):
    """A throwaway TLS server using the hub's own certificate generator."""
    monkeypatch.setattr(agent_tls, "get_appdata_dir", lambda: tmp_path)
    details = agent_tls.ensure_cert()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — stdlib naming
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(agent_tls.cert_path()), str(agent_tls.key_path()))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_port}", details
    server.shutdown()


def test_an_ordinary_client_cannot_reach_the_hub_at_all(tls_server):
    """The defect, pinned as a test: this is what the agent used to do."""
    url, _details = tls_server
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        with httpx.Client(timeout=10) as client:
            client.get(f"{url}/api/system/health")


def test_the_pinned_context_reaches_it(tls_server):
    url, _details = tls_server
    pem, pin = agent_mode.fetch_cert(url)
    assert pin and pem.startswith("-----BEGIN CERTIFICATE-----")
    with httpx.Client(verify=agent_mode._pinned_ssl_context(pem), timeout=10) as client:
        assert client.get(f"{url}/api/system/health").status_code == 200


def test_the_pin_is_enforced_by_the_handshake_not_beside_it(tls_server, tmp_path):
    """A DIFFERENT certificate must fail inside TLS, so there is no window between
    checking the pin and using the connection."""
    url, _details = tls_server
    other = agent_tls.ensure_cert(force=True)  # a new certificate, same generator
    assert other["fingerprint_sha256"] != agent_mode.fetch_cert(url)[1]
    stale_pem = agent_tls.cert_path().read_text()
    with pytest.raises(httpx.ConnectError):
        with httpx.Client(verify=agent_mode._pinned_ssl_context(stale_pem), timeout=10) as c:
            c.get(f"{url}/api/system/health")


def test_hostname_verification_survives_pinning(tls_server):
    """Pinning must not be bought by turning off SAN checking: a certificate for the
    wrong name is still wrong, and `verify=False` plus a fingerprint comparison would
    have thrown this away."""
    url, _details = tls_server
    pem, _pin = agent_mode.fetch_cert(url)
    ctx = agent_mode._pinned_ssl_context(pem)
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_make_client_stops_when_the_certificate_changed(tls_server, monkeypatch):
    url, _details = tls_server
    pem, pin = agent_mode.fetch_cert(url)
    state = agent_mode.AgentState(
        hub_url=url, agent_id="a", private_key_pem="x", cert_pin_sha256=pin, cert_pem=pem
    )
    with agent_mode.make_client(state) as client:
        assert client.get("/api/system/health").status_code == 200

    monkeypatch.setattr(agent_mode, "cert_fingerprint", lambda _u: "b" * 64)
    with pytest.raises(agent_mode.AgentError, match="certificate changed"):
        agent_mode.make_client(state)


def test_an_old_state_file_without_the_certificate_still_works(tls_server):
    """State written before the certificate was stored must not brick the agent: the
    fingerprint already proves which certificate to refetch."""
    url, _details = tls_server
    _pem, pin = agent_mode.fetch_cert(url)
    state = agent_mode.AgentState(
        hub_url=url, agent_id="a", private_key_pem="x", cert_pin_sha256=pin, cert_pem=""
    )
    with agent_mode.make_client(state) as client:
        assert client.get("/api/system/health").status_code == 200


# --- addresses the operator is told to use -------------------------------------
def test_no_link_local_address_is_ever_offered(monkeypatch, tmp_path):
    """An fe80:: literal is meaningless without a scope id, and this list is what a
    human types on another machine."""
    monkeypatch.setattr(agent_tls, "get_appdata_dir", lambda: tmp_path)

    def fake_getaddrinfo(*_a, **_k):
        return [
            (0, 0, 0, "", ("192.168.3.86", 0)),
            (0, 0, 0, "", ("fe80::fb94:7e9b:3011:b548%12", 0)),
            (0, 0, 0, "", ("169.254.1.1", 0)),
        ]

    monkeypatch.setattr(agent_tls.socket, "getaddrinfo", fake_getaddrinfo)
    addresses = agent_tls.local_addresses()
    assert "192.168.3.86" in addresses
    assert not any(a.startswith("fe80") for a in addresses), addresses
    assert "169.254.1.1" not in addresses, "IPv4 link-local is just as useless"
