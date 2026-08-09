"""Tests for the pure-Python (no-nmap) discovery helpers."""

from __future__ import annotations

import asyncio
import ipaddress

import pytest

from app.services import discovery_python
from app.services.discovery_python import (
    PROBE_CEIL,
    PROBE_FLOOR,
    PROBE_INITIAL,
    SECOND_PASS_MIN,
    ScanTargetError,
    _hosts_to_sweep,
    _probe_deadline,
    _probe_estimator,
    parse_arp_table,
)

WINDOWS_ARP = """
Interface: 192.168.1.10 --- 0x2
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.20          11-22-33-44-55-66     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
  239.255.255.250       01-00-5e-7f-ff-fa     static
"""


def test_parse_arp_filters_broadcast_and_multicast():
    table = parse_arp_table(WINDOWS_ARP)
    assert table == {
        "192.168.1.1": "AA:BB:CC:DD:EE:FF",
        "192.168.1.20": "11:22:33:44:55:66",
    }


def test_parse_arp_empty():
    assert parse_arp_table("") == {}


def test_hosts_to_sweep_small_subnet_not_capped():
    hosts, note = _hosts_to_sweep("192.168.1.0/24")
    assert len(hosts) == 254
    assert note == ""
    assert "192.168.1.1" in hosts and "192.168.1.254" in hosts


def test_hosts_to_sweep_caps_large_subnet():
    hosts, note = _hosts_to_sweep("10.0.0.0/8")
    assert len(hosts) <= 1024
    assert note  # a "capped" note is produced


# --- the cap must narrow the network it was ASKED about ------------------------------
def test_a_capped_sweep_stays_inside_the_requested_network(monkeypatch):
    """The first thing anyone does when devices are missing is widen the range.

    That used to be a no-op: the cap threw the requested target away and rebuilt a /24
    around the machine's own address, so asking a 192.168.3.x machine to scan
    10.20.0.0/16 swept 192.168.3.0/24 — none of the requested addresses — and reported
    success. Measured, not theorised: it returned 192.168.3.1 .. 192.168.3.254.
    """

    class _Info:
        local_ip = "192.168.3.86"

    monkeypatch.setattr(discovery_python, "get_network_info", lambda: _Info())
    hosts, note = _hosts_to_sweep("10.20.0.0/16")
    net = ipaddress.IPv4Network("10.20.0.0/16")
    assert hosts, "something must be swept"
    assert all(ipaddress.IPv4Address(h) in net for h in hosts), hosts[:3]
    assert note


def test_when_the_machine_is_inside_the_wide_network_the_window_is_around_it(monkeypatch):
    class _Info:
        local_ip = "10.20.4.37"

    monkeypatch.setattr(discovery_python, "get_network_info", lambda: _Info())
    hosts, _note = _hosts_to_sweep("10.20.0.0/21")
    assert hosts[0] == "10.20.4.1" and hosts[-1] == "10.20.4.254"


def test_the_note_says_how_many_addresses_were_skipped(monkeypatch):
    """A silent cap is indistinguishable from a small network. The number has to be in
    the message, because 'some devices are missing' is exactly what it looks like."""

    class _Info:
        local_ip = "10.20.4.37"

    monkeypatch.setattr(discovery_python, "get_network_info", lambda: _Info())
    hosts, note = _hosts_to_sweep("10.20.0.0/21")
    skipped = 2046 - len(hosts)
    assert str(skipped) in note and str(len(hosts)) in note


def test_a_tunnel_address_is_refused_instead_of_scanning_one_host():
    """A /32 is a VPN address, not a network. It slipped through the size check
    (num_addresses - 2 is negative), swept the single address — the machine itself —
    and reported a successful scan with an empty note."""
    with pytest.raises(ScanTargetError) as exc:
        _hosts_to_sweep("100.79.253.90/32")
    assert "VPN" in str(exc.value)
    with pytest.raises(ScanTargetError):
        _hosts_to_sweep("10.0.0.0/31")


# --- the broadcast test must know the actual network ---------------------------------
WIDE_ARP = """
  10.0.4.255            11-22-33-44-55-66     dynamic
  10.0.7.255            aa-bb-cc-dd-ee-ff     static
  225.1.2.3             00-11-22-33-44-55     static
  240.0.0.9             00-11-22-33-44-56     static
"""


def test_a_dot255_host_survives_on_a_network_wider_than_24():
    """On a /21 the only broadcast address is the last one. Deleting every address that
    ends in .255 deletes seven real hosts — permanently, on every scan."""
    table = parse_arp_table(WIDE_ARP, "10.0.0.0/21")
    assert table["10.0.4.255"] == "11:22:33:44:55:66"
    assert "10.0.7.255" not in table, "that one IS the broadcast address"


def test_multicast_and_reserved_are_dropped_by_range_not_by_first_octet():
    """The old test listed 224/239/255 as strings, so 225..238 and all of 240/4 walked
    through and became devices."""
    table = parse_arp_table(WIDE_ARP, "10.0.0.0/21")
    assert "225.1.2.3" not in table
    assert "240.0.0.9" not in table


def test_without_a_network_the_old_dot24_guess_is_kept():
    assert parse_arp_table(WINDOWS_ARP) == {
        "192.168.1.1": "AA:BB:CC:DD:EE:FF",
        "192.168.1.20": "11:22:33:44:55:66",
    }


# --- a completed handshake is proof of life ------------------------------------------
def test_a_host_that_answers_is_reported_even_with_no_arp_entry(monkeypatch):
    """Existence used to be decided by `arp -a` alone. A device that completed a TCP
    handshake but that the OS kept no neighbour row for simply did not exist as far as
    the app was concerned — and every condition that suppresses an ARP entry (another
    segment, a purged cache, an isolating AP) became a disappearance rather than a
    degraded record."""
    monkeypatch.setattr(discovery_python, "_hosts_to_sweep", lambda t: (["10.0.0.5"], ""))
    monkeypatch.setattr(discovery_python, "_read_arp_table", lambda network="": {})
    monkeypatch.setattr(discovery_python, "_local_device", lambda: None)

    async def fake_sweep(hosts, est, second_pass=False):
        return {"10.0.0.5"}

    monkeypatch.setattr(discovery_python, "_sweep", fake_sweep)

    monkeypatch.setattr(discovery_python, "_resolve", lambda ip: "")
    devices = asyncio.run(discovery_python.discover_python("10.0.0.0/24"))
    assert [d["ip"] for d in devices] == ["10.0.0.5"]
    assert devices[0]["mac"] == "", "honest: ARP never told us its hardware address"
    assert devices[0]["status"] == "online"


def test_the_probe_reports_which_address_answered():
    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        original_port = discovery_python.PROBE_PORT
        discovery_python.PROBE_PORT = port
        try:
            sem = asyncio.Semaphore(4)
            est = _probe_estimator("127.0.0.0/24")
            return await discovery_python._probe("127.0.0.1", sem, est, False)
        finally:
            discovery_python.PROBE_PORT = original_port
            server.close()
            await server.wait_closed()

    assert asyncio.run(scenario()) == "127.0.0.1"


def test_coverage_is_published_not_just_logged(monkeypatch):
    from app.services.progress import scan_progress

    monkeypatch.setattr(
        discovery_python, "_hosts_to_sweep", lambda t: (["10.0.0.5"], "فُحص جزء فقط")
    )
    monkeypatch.setattr(discovery_python, "_read_arp_table", lambda network="": {})
    monkeypatch.setattr(discovery_python, "_local_device", lambda: None)

    async def fake_sweep(hosts, est, second_pass=False):
        return set()

    monkeypatch.setattr(discovery_python, "_sweep", fake_sweep)
    scan_progress.begin("10.0.0.0/24")
    asyncio.run(discovery_python.discover_python("10.0.0.0/24"))
    assert scan_progress.coverage == "فُحص جزء فقط"
    assert "coverage" in scan_progress.to_dict()


def test_probe_estimator_is_per_subnet():
    a1 = _probe_estimator("192.168.50.0/24")
    a2 = _probe_estimator("192.168.50.7/24")  # same CIDR after normalization
    b = _probe_estimator("10.9.0.0/24")
    assert a1 is a2  # one estimator per subnet, reused across scans
    assert a1 is not b
    assert a1.current() == PROBE_INITIAL  # cold start == old fixed timeout


def test_first_pass_deadline_is_the_learned_rto():
    est = _probe_estimator("172.16.0.0/24")
    for _ in range(30):
        est.on_sample(0.01)  # fast LAN hosts answer
    # First pass tracks the RTO and speeds up (down to the floor) — no fixed 1.2s.
    assert _probe_deadline(est, second_pass=False) == est.current() == PROBE_FLOOR


def test_second_pass_never_drops_below_the_sleeper_window():
    # Even when the estimator has collapsed to the floor on a fast LAN, the retry
    # pass must keep a wide window so a DTIM-sleeping phone is still caught. This
    # is the guard against regressing the deliberate 0.4s -> 1.2s sleeper fix.
    est = _probe_estimator("172.16.9.0/24")
    for _ in range(50):
        est.on_sample(0.005)
    assert est.current() == PROBE_FLOOR  # collapsed to floor
    for _ in range(200):
        assert _probe_deadline(est, second_pass=True) >= SECOND_PASS_MIN
    # And it stays within a sane ceiling (floor/ceil are sane).
    assert PROBE_FLOOR < SECOND_PASS_MIN <= PROBE_CEIL + 1.0


def test_the_tunnel_refusal_reaches_the_operator_not_just_the_log(monkeypatch):
    """Raising is only half of it: the message has to arrive where the user reads it.

    The scan runs in the background, so an exception that never reaches scan_progress
    shows up as a scan that simply stopped — the silent failure this release is about.
    """
    import asyncio as _asyncio

    from app.services.discovery import DiscoveryError, scan_network
    from app.services.progress import scan_progress

    monkeypatch.setattr("app.services.discovery._choose_method", lambda: "python")
    scan_progress.begin("100.79.253.90/32")
    with pytest.raises(DiscoveryError):
        _asyncio.run(scan_network("100.79.253.90/32"))
    assert scan_progress.phase == "error"
    assert "VPN" in (scan_progress.error or "")
