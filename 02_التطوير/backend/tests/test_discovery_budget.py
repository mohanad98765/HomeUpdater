"""The nmap scan budget is now derived from host count and clamped, instead of a
flat 600s shared by a /24 and a /16."""

from __future__ import annotations

from app.services.discovery import (
    DEFAULT_SCAN_TIMEOUT_SECONDS,
    MIN_SCAN_BUDGET_SECONDS,
    _scan_budget,
)


def test_small_subnet_gets_a_tight_budget():
    # A /24 (254 hosts) must not sit on the full 600s ceiling.
    budget = _scan_budget(254, DEFAULT_SCAN_TIMEOUT_SECONDS)
    assert MIN_SCAN_BUDGET_SECONDS <= budget < DEFAULT_SCAN_TIMEOUT_SECONDS


def test_tiny_subnet_clamped_to_floor():
    assert _scan_budget(4, DEFAULT_SCAN_TIMEOUT_SECONDS) == MIN_SCAN_BUDGET_SECONDS


def test_huge_subnet_clamped_to_ceiling():
    assert _scan_budget(100_000, DEFAULT_SCAN_TIMEOUT_SECONDS) == DEFAULT_SCAN_TIMEOUT_SECONDS


def test_unknown_host_count_uses_ceiling():
    assert _scan_budget(0, DEFAULT_SCAN_TIMEOUT_SECONDS) == DEFAULT_SCAN_TIMEOUT_SECONDS
    assert _scan_budget(-5, DEFAULT_SCAN_TIMEOUT_SECONDS) == DEFAULT_SCAN_TIMEOUT_SECONDS


def test_budget_is_monotonic_in_host_count():
    small = _scan_budget(120, DEFAULT_SCAN_TIMEOUT_SECONDS)
    big = _scan_budget(700, DEFAULT_SCAN_TIMEOUT_SECONDS)
    assert small <= big
