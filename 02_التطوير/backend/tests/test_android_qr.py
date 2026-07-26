"""QR pairing — the parts that must hold whether or not the phone adopts our name.

The one thing nobody could verify about this flow is whether a phone that scanned our
code advertises the service name from the QR's ``S`` field or, as in the only real
capture this repository has, its own ``adb-<serial>-<random>`` guid. So the tests below
assert that the flow works in BOTH cases: an unverified fact must not be load-bearing.

They also assert the things that are about the credential rather than the protocol: one
session at a time, the password never persisted or logged, a code that stops working
when the window closes, and two phones producing a question instead of a coin flip.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import android_qr

H = {"X-HomeUpdater": "1"}

# The real capture, from a Samsung on this network (see test_android.py). Note the
# instance is the phone's own guid, NOT a name any host chose.
# Both rows, because that is what a real phone advertises: the connect service is how
# the hub learns which port to report, and a fake that omits it makes every successful
# test sit out the full discovery deadline.
GUID_ROW = (
    "List of discovered mdns services\n"
    "adb-RFCW70YDHHB-hqcfQV\t_adb-tls-pairing._tcp\t192.168.3.30:34887\n"
    "adb-RFCW70YDHHB-hqcfQV\t_adb-tls-connect._tcp\t192.168.3.30:34677\n"
)
CONNECT_ROW = "x\t_adb-tls-connect._tcp\t{address}:5555\n"


@pytest.fixture(autouse=True)
def _clean():
    android_qr.reset_for_tests()
    yield
    android_qr.reset_for_tests()


@pytest.fixture
def adb(monkeypatch):
    """A fake adb whose `mdns services` output the test controls."""
    state = {"output": "List of discovered mdns services\n", "pairs": [], "fail": ""}

    def fake_run(args, timeout=30.0, input_text=None):
        if args[:2] == ["mdns", "services"]:
            return 0, state["output"], ""
        if args[0] == "start-server":
            return 0, "", ""
        if args[0] == "pair":
            state["pairs"].append((args[1], input_text.strip() if input_text else ""))
            if state["fail"]:
                return 1, "", state["fail"]
            return 0, "Successfully paired to " + args[1], ""
        return 0, "", ""

    monkeypatch.setattr(android_qr, "_run_adb_blocking", fake_run)
    monkeypatch.setattr(android_qr, "_have_adb", lambda: True)
    monkeypatch.setattr("app.services.android._run_adb_blocking", fake_run)
    return state


# --- the payload ---------------------------------------------------------------
def test_the_payload_is_the_aosp_template():
    payload = android_qr.build_payload("homeupdater-abc12345", "483920")
    assert payload == "WIFI:T:ADB;S:homeupdater-abc12345;P:483920;;"


def test_generated_fields_cannot_break_the_payload():
    """Both fields come from a fixed alphabet, so nothing needs escaping and no outside
    input can reach this string."""
    for _ in range(20):
        name, password = android_qr._new_service_name(), android_qr._new_password()
        assert ";" not in name and ":" not in name
        assert password.isdigit() and len(password) == 6
        assert android_qr.build_payload(name, password).count(";") == 4


def test_the_code_renders_as_an_svg_with_no_script():
    svg = android_qr.render_qr_svg("WIFI:T:ADB;S:x;P:123456;;")
    assert svg.lstrip().startswith("<svg")
    assert "<script" not in svg.lower(), "this SVG is inlined into the page"


# --- the unverified assumption must not matter ---------------------------------
def test_a_phone_advertising_its_own_guid_still_pairs(adb):
    """The case our only real capture shows: the instance is nothing we chose."""
    session = asyncio.run(android_qr.start())
    adb["output"] = GUID_ROW
    asyncio.run(android_qr._watch(session))
    assert session.status == "paired", session.error
    assert adb["pairs"] == [("192.168.3.30:34887", session_password := adb["pairs"][0][1])]
    assert session_password.isdigit()


def test_a_phone_adopting_our_name_also_pairs(adb):
    session = asyncio.run(android_qr.start())
    adb["output"] = (
        "List of discovered mdns services\n"
        f"{session.service_name}\t_adb-tls-pairing._tcp\t192.168.3.44:40001\n"
        + CONNECT_ROW.format(address="192.168.3.44")
    )
    asyncio.run(android_qr._watch(session))
    assert session.status == "paired"
    assert adb["pairs"][0][0] == "192.168.3.44:40001"


def test_our_name_is_preferred_when_both_appear(adb):
    """If the phone does adopt the name, that is a real signal — used to pick between
    candidates, never required."""
    session = asyncio.run(android_qr.start())
    adb["output"] = (
        "List of discovered mdns services\n"
        "adb-SOMEONE-ELSE\t_adb-tls-pairing._tcp\t192.168.3.99:1111\n"
        f"{session.service_name}\t_adb-tls-pairing._tcp\t192.168.3.44:2222\n"
        + CONNECT_ROW.format(address="192.168.3.44")
    )
    asyncio.run(android_qr._watch(session))
    assert session.status == "paired"
    assert adb["pairs"][0][0] == "192.168.3.44:2222", "our own code's phone, not a stranger's"


def test_services_already_present_are_ignored(adb):
    """A phone that was already advertising before the code was shown did not scan it,
    so pairing with it would send our password somewhere unrelated."""
    adb["output"] = GUID_ROW
    session = asyncio.run(android_qr.start())
    assert "adb-RFCW70YDHHB-hqcfQV" in session.known_instances
    android_qr.SESSION_TTL_SECONDS = 1
    session.expires_at = session.expires_at.replace(year=2000)
    asyncio.run(android_qr._watch(session))
    assert session.status == "expired"
    assert adb["pairs"] == [], "nothing was paired"


def test_two_new_phones_produce_a_question_not_a_coin_flip(adb):
    session = asyncio.run(android_qr.start())
    adb["output"] = (
        "List of discovered mdns services\n"
        "adb-PHONE-A\t_adb-tls-pairing._tcp\t192.168.3.10:1111\n"
        "adb-PHONE-B\t_adb-tls-pairing._tcp\t192.168.3.11:2222\n"
        + CONNECT_ROW.format(address="192.168.3.11")
    )
    asyncio.run(android_qr._watch(session))
    assert session.status == "choose"
    assert adb["pairs"] == [], "the password was not handed to either one yet"
    assert {c["instance"] for c in session.candidates} == {"adb-PHONE-A", "adb-PHONE-B"}

    asyncio.run(android_qr.choose("adb-PHONE-B"))
    assert session.status == "paired"
    assert adb["pairs"][0][0] == "192.168.3.11:2222"


def test_choosing_a_phone_that_is_gone_is_refused(adb):
    session = asyncio.run(android_qr.start())
    session.status = "choose"
    session.candidates = [{"instance": "adb-A", "address": "1.2.3.4", "port": 1}]
    with pytest.raises(android_qr.AndroidError):
        asyncio.run(android_qr.choose("adb-NOT-THERE"))


# --- the credential ------------------------------------------------------------
def test_only_one_session_can_be_live(adb):
    first = asyncio.run(android_qr.start())
    second = asyncio.run(android_qr.start())
    assert first.id != second.id
    assert android_qr.current().id == second.id
    assert first.password == "", "the replaced session's password is forgotten"


def test_cancelling_forgets_the_password_and_the_code(adb):
    session = asyncio.run(android_qr.start())
    assert session.password and session.payload
    asyncio.run(android_qr.cancel())
    assert android_qr.current() is None
    assert session.password == "" and session.payload == ""


def test_a_successful_pairing_drops_the_password(adb):
    session = asyncio.run(android_qr.start())
    adb["output"] = GUID_ROW
    asyncio.run(android_qr._watch(session))
    assert session.status == "paired"
    assert session.password == "", "it has done its job"
    assert session.payload == ""


def test_the_public_view_carries_no_bare_password(adb):
    session = asyncio.run(android_qr.start())
    pub = session.public()
    assert "password" not in pub
    # It is inside the payload because the QR is useless without it, and nowhere else.
    assert session.password in pub["payload"]
    assert pub["payload"].count(session.password) == 1


def test_an_expired_session_reports_expired_not_failed(adb):
    session = asyncio.run(android_qr.start())
    session.expires_at = session.expires_at.replace(year=2000)
    asyncio.run(android_qr._watch(session))
    assert session.status == "expired"


def test_a_failed_pair_is_reported_with_its_reason(adb):
    adb["fail"] = "failed to authenticate to 192.168.3.30:34887"
    session = asyncio.run(android_qr.start())
    adb["output"] = GUID_ROW
    asyncio.run(android_qr._watch(session))
    assert session.status == "failed"
    assert "authenticate" in session.error


# --- the endpoints -------------------------------------------------------------
def test_the_svg_endpoint_refuses_to_cache_the_credential(client, adb):
    client.post("/api/android/pair/qr", headers=H)
    r = client.get("/api/android/pair/qr.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "no-store" in r.headers["cache-control"]


def test_there_is_no_code_to_fetch_without_a_session(client):
    assert client.get("/api/android/pair/qr.svg").status_code == 404


def test_status_says_none_once_the_session_is_gone(client, adb):
    client.post("/api/android/pair/qr", headers=H)
    assert client.get("/api/android/pair/qr").json()["status"] == "waiting"
    client.request("DELETE", "/api/android/pair/qr", headers=H)
    assert client.get("/api/android/pair/qr").json() == {"status": "none"}


def test_the_session_is_never_written_to_the_database(client, adb):
    """It is a two-minute credential. Persisting it would outlive its own window."""
    client.post("/api/android/pair/qr", headers=H)
    tables = client.get("/api/audit/events?limit=20").json()["events"]
    assert not any("pair" in str(e).lower() and "WIFI:T:ADB" in str(e) for e in tables)
