"""Tests for the pure-Python (no-nmap) discovery helpers."""

from __future__ import annotations

from app.services.discovery_python import (
    PROBE_CEIL,
    PROBE_FLOOR,
    PROBE_INITIAL,
    SECOND_PASS_MIN,
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
