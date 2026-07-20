"""Device-type classification — regression tests for the phone-scan fix.

Phones from Apple/Samsung/Huawei/Xiaomi must classify as `phone`, and the
hostname must win over the vendor OUI. The Huawei case is a regression: it used
to classify as `router` because "huawei tech" sat in the router-vendor list and
the router check ran first.
"""

from __future__ import annotations

import pytest

from app.services.network_utils import classify_device


@pytest.mark.parametrize(
    "hostname, vendor, expected",
    [
        # Huawei phone — the regression (was 'router')
        ("", "Huawei Technologies Co.,Ltd", "phone"),
        # consumer phone OUIs lean phone
        ("", "Apple, Inc.", "phone"),
        ("", "Samsung Electronics", "phone"),
        ("", "Xiaomi Communications", "phone"),
        # hostname is the most specific signal and wins over the vendor
        ("my-router", "Huawei Technologies", "router"),
        ("Galaxy-S21", "Samsung Electronics", "phone"),
        ("iPhone", "", "phone"),
        ("living-room-tv", "", "smart_tv"),
        # router-only vendors still classify as router
        ("", "TP-Link Technologies", "router"),
        ("", "NETGEAR", "router"),
        # others
        ("", "Dell Inc.", "computer"),
        ("", "Espressif Inc.", "iot"),
        ("", "", "unknown"),
    ],
)
def test_classify_device(hostname, vendor, expected):
    assert classify_device(hostname, vendor) == expected
