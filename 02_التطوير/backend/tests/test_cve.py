"""Tests for the CVE (NVD vulnerability) service and endpoints — NVD is mocked."""

from __future__ import annotations

from app.services import cve

SAMPLE_NVD = {
    "totalResults": 3,
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2020-0001",
                "published": "2020-01-01T00:00:00",
                "descriptions": [{"lang": "en", "value": "Low issue"}],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 3.1, "baseSeverity": "LOW"}}]
                },
            }
        },
        {
            "cve": {
                "id": "CVE-2021-9999",
                "published": "2021-06-01T00:00:00",
                "descriptions": [{"lang": "en", "value": "Critical issue"}],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]
                },
            }
        },
        {
            "cve": {
                "id": "CVE-2019-1234",
                "published": "2019-03-01T00:00:00",
                "descriptions": [{"lang": "en", "value": "High issue"}],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}]
                },
            }
        },
    ],
}


async def _fake_fetch(keyword, results_per_page=100):
    return SAMPLE_NVD


def test_parse_cves_sorts_by_severity_then_recency():
    out = cve.parse_cves(SAMPLE_NVD, limit=8)
    assert [c["id"] for c in out] == ["CVE-2021-9999", "CVE-2019-1234", "CVE-2020-0001"]
    assert out[0]["severity"] == "CRITICAL"
    assert out[0]["url"].endswith("CVE-2021-9999")


def test_parse_cves_respects_limit():
    assert len(cve.parse_cves(SAMPLE_NVD, limit=1)) == 1


def test_cves_endpoint_fetches_then_caches(client, monkeypatch):
    monkeypatch.setattr(cve, "_fetch_nvd", _fake_fetch)
    r = client.get("/api/security/cves", params={"keyword": "TP-Link"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_results"] == 3
    assert body["cached"] is False
    assert body["cves"][0]["severity"] == "CRITICAL"

    # A second call is served from the DB cache (no second fetch).
    r2 = client.get("/api/security/cves", params={"keyword": "TP-Link"})
    assert r2.json()["cached"] is True


def test_cves_endpoint_503_when_no_cache_and_nvd_down(client, monkeypatch):
    async def boom(keyword, results_per_page=100):
        raise RuntimeError("network down")

    monkeypatch.setattr(cve, "_fetch_nvd", boom)
    r = client.get("/api/security/cves", params={"keyword": "UnseenVendor"})
    assert r.status_code == 503


def test_overview_empty(client):
    r = client.get("/api/security/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["devices"] == []
    assert body["vendors_total"] == 0
