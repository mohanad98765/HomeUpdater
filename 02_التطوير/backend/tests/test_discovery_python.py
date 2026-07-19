"""Tests for the pure-Python (no-nmap) discovery helpers."""

from __future__ import annotations

from app.services.discovery_python import _hosts_to_sweep, parse_arp_table

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
