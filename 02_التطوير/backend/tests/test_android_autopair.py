"""Pairing without mDNS — the path built after the network refused to carry multicast.

The measurement that produced this module: on the target network the phone answers a
ping in 40ms and sends zero mDNS packets in sixty seconds, while five arrive from other
hosts. The PC is on Ethernet, the phone on Wi-Fi, and the router does not forward
multicast between them. Every Android pairing flow assumes the host can hear the phone
announce a randomly chosen port; here it cannot, and six QR attempts failed with nothing
wrong in the app.

The operator these tests protect has no technical expertise. That is the constraint that
decides the design, so it is what the tests assert: the code is the ONLY thing a person
supplies, a wrong code is told apart from a wrong port, and a closed pairing screen
produces a sentence someone can act on rather than a stack trace.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import android_autopair as ap
from app.services.android import AndroidError

H = {"X-HomeUpdater": "1"}


@pytest.fixture
def scan(monkeypatch):
    """Control what the port scan 'finds' without opening a socket."""
    state = {"ports": [], "pairs": [], "pair_result": {}, "connects": {}}

    async def fake_find(host, first=None, last=None):
        return list(state["ports"])

    def fake_pair(host, port, code):
        state["pairs"].append((host, port, code))
        return state["pair_result"].get(port, (False, "failed to connect"))

    def fake_run(args, timeout=30.0, input_text=None):
        if args[0] == "connect":
            target = args[1]
            if state["connects"].get(target):
                return 0, f"connected to {target}", ""
            return 1, "", "failed to connect"
        return 0, "", ""

    monkeypatch.setattr(ap, "find_open_ports", fake_find)
    monkeypatch.setattr(ap, "_pair_blocking", fake_pair)
    monkeypatch.setattr(ap, "_run_adb_blocking", fake_run)
    monkeypatch.setattr(ap, "_have_adb", lambda: True)
    return state


# --- what the operator has to supply -------------------------------------------
def test_the_code_is_the_only_thing_a_person_provides(scan):
    """No port anywhere in the call. That is the whole point: a shop owner cannot be
    asked to read a random port off a phone, and the hub can find it."""
    scan["ports"] = [30001, 34887]
    scan["pair_result"] = {34887: (True, "Successfully paired to 192.168.3.24:34887")}
    out = asyncio.run(ap.pair_with_code("192.168.3.24", "566925"))
    assert out["paired"] is True
    assert out["pairing_port"] == 34887
    assert [p[2] for p in scan["pairs"]] == ["566925", "566925"]


def test_a_six_digit_code_is_required_before_anything_is_scanned(scan):
    for bad in ("", "12345", "1234567", "abcdef", "12 34 56"):
        with pytest.raises(AndroidError, match="٦ أرقام"):
            asyncio.run(ap.pair_with_code("192.168.3.24", bad))
    assert scan["pairs"] == [], "nothing was probed for an obviously invalid code"


def test_a_closed_pairing_screen_says_so_in_words_a_person_can_act_on(scan):
    """The single most likely mistake: the screen was closed, which closes the port."""
    scan["ports"] = []
    with pytest.raises(AndroidError) as err:
        asyncio.run(ap.pair_with_code("192.168.3.24", "566925"))
    message = str(err.value)
    assert "إقران جهاز برمز الإقران" in message
    assert "مفتوحة" in message
    assert "port" not in message.lower(), "no jargon in the sentence the operator reads"


def test_a_wrong_code_is_not_retried_against_every_other_port(scan):
    """A wrong code on the right port is a certain failure everywhere else, and burning
    twenty seconds re-proving it is time taken from someone standing at their phone."""
    scan["ports"] = [30001, 34887, 41000]
    scan["pair_result"] = {30001: (False, "failed to authenticate to the device")}
    with pytest.raises(AndroidError, match="الرمز غير صحيح"):
        asyncio.run(ap.pair_with_code("192.168.3.24", "000000"))
    assert len(scan["pairs"]) == 1, "it stopped at the first definitive answer"


def test_wrong_ports_are_passed_over_quietly(scan):
    """Most candidates are just other listeners; that is not an error worth reporting."""
    scan["ports"] = [30001, 30002, 34887]
    scan["pair_result"] = {34887: (True, "Successfully paired")}
    out = asyncio.run(ap.pair_with_code("192.168.3.24", "566925"))
    assert out["pairing_port"] == 34887
    assert len(scan["pairs"]) == 3


def test_no_port_accepting_the_code_reports_the_likely_reason(scan):
    scan["ports"] = [30001, 30002]
    with pytest.raises(AndroidError, match="انتهت صلاحية الرمز"):
        asyncio.run(ap.pair_with_code("192.168.3.24", "566925"))


def test_a_bad_host_is_refused_before_any_socket_is_opened(scan):
    for bad in ("-rf", "1.2.3.4; rm", "$(whoami)"):
        with pytest.raises(AndroidError):
            asyncio.run(ap.pair_with_code(bad, "566925"))
    assert scan["pairs"] == []


# --- finding the connect port the same way -------------------------------------
def test_the_connect_port_is_also_found_by_looking_not_listening(scan):
    scan["ports"] = [34887, 34677]
    scan["connects"] = {"192.168.3.24:34677": True}
    port = asyncio.run(ap.find_connect_port("192.168.3.24", exclude=34887))
    assert port == 34677


def test_the_pairing_port_is_not_offered_as_the_connect_port(scan):
    scan["ports"] = [34887]
    scan["connects"] = {"192.168.3.24:34887": True}
    assert asyncio.run(ap.find_connect_port("192.168.3.24", exclude=34887)) is None


# --- the scan itself ------------------------------------------------------------
def test_the_scanned_range_matches_what_this_phone_actually_used():
    """34887 and 34677 are the ports the real phone published in the capture this
    repository holds. A range that excluded them would look fine and never work."""
    lo, hi = ap.PORT_RANGE
    assert lo <= 34677 < hi and lo <= 34887 < hi


def test_only_the_chosen_host_is_probed(monkeypatch):
    """A pairing flow has no business touching anything but the phone the operator
    picked."""
    seen = []

    async def fake_open(host, port):
        seen.append(host)
        raise OSError("closed")

    monkeypatch.setattr(ap.asyncio, "open_connection", fake_open)
    asyncio.run(ap.find_open_ports("192.168.3.24", 30000, 30020))
    assert set(seen) == {"192.168.3.24"}


# --- the endpoints ---------------------------------------------------------------
def test_candidates_come_from_the_scan_the_app_already_did(client):
    r = client.get("/api/android/pair/candidates")
    assert r.status_code == 200
    body = r.json()
    assert "candidates" in body and isinstance(body["candidates"], list)


def test_auto_pair_rejects_a_malformed_code_at_the_edge(client):
    r = client.post(
        "/api/android/pair/auto", json={"host": "192.168.3.24", "code": "12345"}, headers=H
    )
    assert r.status_code == 422, "pydantic refuses it before any scanning happens"
