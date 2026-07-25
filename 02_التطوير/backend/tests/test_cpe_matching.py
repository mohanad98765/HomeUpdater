"""Precise (CPE) CVE matching: version normalization, the curated map, /precise.

The whole point of this path is that a finding must be DEFENSIBLE: it names the
exact installed version and the range that made a CVE apply. So the tests here
mostly guard the ways a precise claim could quietly become a guess — an unmapped
product, an un-comparable version string, or a keyword result leaking into the
precise output.
"""

from __future__ import annotations

import asyncio

from app.services import cpe, cve

CSRF = {"X-HomeUpdater": "1"}


# --- version normalization: real winget strings ------------------------------
def test_plain_versions_pass_through():
    assert cpe.normalize_version("26.02") == "26.02"
    assert cpe.normalize_version("150.0.7871.187") == "150.0.7871.187"
    assert cpe.normalize_version("8") == "8"


def test_single_leading_token_is_stripped():
    """AnyDesk really reports 'ad 9.7.11' in winget list output."""
    assert cpe.normalize_version("ad 9.7.11") == "9.7.11"


def test_unknown_markers_are_refused():
    """winget's '> x' means 'at least, actual unknown'. Matching on it would be a
    guess dressed as a precise finding, so it must fail closed."""
    assert cpe.normalize_version("> 3.13.5") is None
    assert cpe.normalize_version("< 1.0") is None
    assert cpe.normalize_version("Unknown") is None


def test_msix_identity_leaking_into_the_version_column_is_refused():
    raw = "MSIX\\MicrosoftCorporationII.WinAppRuntime.Main.1.8_8000.921.1539.0_x64 8000.921.1539.0"
    assert cpe.normalize_version(raw) is None


def test_empty_and_garbage_versions_are_refused():
    assert cpe.normalize_version("") is None
    assert cpe.normalize_version("   ") is None
    assert cpe.normalize_version("not-a-version") is None


# --- the curated map --------------------------------------------------------
def test_unmapped_product_resolves_to_none():
    assert cpe.resolve("Totally.Unknown.Product", "1.2.3") is None


def test_cpe_name_shape_is_valid_2_3():
    identity = cpe.CpeIdentity(vendor="7-zip", product="7-zip", version="26.02")
    assert identity.cpe_name == "cpe:2.3:a:7-zip:7-zip:26.02:*:*:*:*:*:*:*"
    assert identity.cpe_name.count(":") == 12  # cpe:2.3 + 11 components


def test_every_curated_entry_is_well_formed():
    """A malformed entry would silently produce a CPE NVD can never match."""
    assert cpe.CPE_MAP, "the curated map must not be empty"
    for winget_id, e in cpe.CPE_MAP.items():
        assert winget_id and " " not in winget_id, winget_id
        assert e.vendor and ":" not in e.vendor and e.vendor == e.vendor.lower(), e.vendor
        assert e.product and ":" not in e.product and e.product == e.product.lower(), e.product
        assert e.confidence in {"high", "medium"}, (winget_id, e.confidence)
        assert e.version_parts in (None, 3, 4), (winget_id, e.version_parts)


def test_known_traps_are_not_mapped():
    """Each of these has a plausible-looking but WRONG CPE; mapping any of them
    would produce confidently false findings, so they must stay unmapped."""
    for trap in (
        "Microsoft.WindowsAppRuntime.1.7",  # microsoft:windows_app = remote desktop client
        "Microsoft.Teams",  # build 26183 vs NVD 1.6.x — incomparable
        "Microsoft.PowerBI",  # only mobile CPEs exist
        "Python.Launcher",  # would duplicate every CPython finding
        "Microsoft.VCRedist.2015+.x64",  # legacy visual_c++ covers 2005-2010 only
    ):
        assert trap not in cpe.CPE_MAP, trap
        assert trap in cpe.UNMAPPABLE, f"{trap} must document WHY it is unmapped"


def test_edge_maps_to_chromium_not_legacy():
    e = cpe.CPE_MAP["Microsoft.Edge"]
    assert (e.vendor, e.product) == ("microsoft", "edge_chromium")


def test_nmap_vendor_is_not_the_winget_publisher():
    e = cpe.CPE_MAP["Insecure.Nmap"]
    assert e.vendor == "nmap", "'Insecure' is the winget publisher, not the CPE vendor"


def test_git_for_windows_revision_is_trimmed_to_upstream():
    """Installed 2.55.0.3 must become upstream 2.55.0 — without the trim the NVD
    query matches nothing and the report would read 'no vulnerabilities'."""
    identity = cpe.resolve("Git.Git", "2.55.0.3")
    assert identity is not None
    assert identity.version == "2.55.0"
    assert identity.cpe_name == "cpe:2.3:a:git:git:2.55.0:*:*:*:*:*:*:*"


def test_short_version_is_padded_where_nvd_uses_three_parts():
    identity = cpe.resolve("GitHub.cli", "2.96")
    assert identity is not None and identity.version == "2.96.0"


def test_four_part_products_are_not_trimmed():
    """Chrome/Edge MUST send the full build; truncating to the major matches nothing."""
    chrome = cpe.resolve("Google.Chrome", "150.0.7871.187")
    assert chrome is not None and chrome.version == "150.0.7871.187"


def test_coverage_reports_the_gap_honestly():
    ids = list(cpe.CPE_MAP)[:2] + ["Nope.One", "Nope.Two"]
    cov = cpe.coverage(ids)
    assert cov["total"] == len(ids)
    assert cov["mapped"] + cov["unmapped"] == cov["total"]
    assert cpe.coverage([])["percent"] == 0.0


# --- reading the version range back out of an NVD response ------------------
_NVD_RESPONSE = {
    "totalResults": 1,
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2024-0001",
                "published": "2024-03-01T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "A heap overflow in the parser."}],
                "metrics": {
                    "cvssMetricV31": [
                        {"cvssData": {"baseScore": 8.8, "baseSeverity": "HIGH"}},
                    ]
                },
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "vulnerable": True,
                                        "criteria": "cpe:2.3:a:7-zip:7-zip:*:*:*:*:*:*:*:*",
                                        "versionEndExcluding": "26.03",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        }
    ],
}


def test_matched_ranges_extracts_the_reason_a_cve_applies():
    ranges = cve.matched_ranges(_NVD_RESPONSE, "7-zip")
    assert len(ranges) == 1
    assert ranges[0]["id"] == "CVE-2024-0001"
    assert ranges[0]["end_excluding"] == "26.03"
    assert ranges[0]["vulnerable"] is True


def test_matched_ranges_ignores_other_products_in_the_same_advisory():
    """An advisory often lists many products; only OUR product's range is evidence."""
    assert cve.matched_ranges(_NVD_RESPONSE, "some-other-product") == []


def _seed_inventory(client, monkeypatch, items: list[tuple[str, str]]) -> None:
    """Seed the inventory through the REAL refresh path (winget mocked), so the
    tests exercise the same code the app runs instead of hand-built sessions."""
    from app.services import software_updates as sw

    async def fake_list():
        return [sw.InstalledSoftwareInfo(pid, pid.split(".")[-1], ver) for pid, ver in items], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    r = client.post("/api/updates/inventory/refresh", headers=CSRF)
    assert r.status_code == 200, r.text


def test_precise_matches_installed_version_and_explains_why(client, monkeypatch):
    """End-to-end on the precise path: the finding must carry the CPE it matched
    AND the version range that made the CVE apply — that is what makes it
    auditable rather than an assertion."""
    monkeypatch.setitem(cpe.CPE_MAP, "7zip.7zip", cpe.CpeEntry("7-zip", "7-zip"))
    _seed_inventory(client, monkeypatch, [("7zip.7zip", "26.02")])

    async def fake_fetch(cpe_name, results_per_page=50):
        assert cpe_name == "cpe:2.3:a:7-zip:7-zip:26.02:*:*:*:*:*:*:*"
        return _NVD_RESPONSE

    monkeypatch.setattr(cve, "fetch_by_cpe", fake_fetch)

    body = client.get("/api/security/precise?refresh_nvd=true").json()
    assert len(body["matched"]) == 1, body
    found = body["matched"][0]
    assert found["cpe_name"] == "cpe:2.3:a:7-zip:7-zip:26.02:*:*:*:*:*:*:*"
    assert found["version"] == "26.02"
    assert found["cves"][0]["id"] == "CVE-2024-0001"
    assert found["cves"][0]["applies_because"]["end_excluding"] == "26.03"

    # A second call is served from the cache — no NVD hit, same answer.
    async def must_not_call(*a, **k):
        raise AssertionError("second call should be served from the 24h cache")

    monkeypatch.setattr(cve, "fetch_by_cpe", must_not_call)
    again = client.get("/api/security/precise?refresh_nvd=true").json()
    assert again["matched"][0]["cves"][0]["id"] == "CVE-2024-0001"


def test_fetch_by_cpe_treats_unknown_cpe_404_as_no_data(monkeypatch):
    class Resp:
        status_code = 404
        headers: dict = {}

        def json(self) -> dict:  # noqa: F811 — httpx.Response API shape
            return {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cve.httpx, "AsyncClient", lambda **kw: Client())
    data = asyncio.run(cve.fetch_by_cpe("cpe:2.3:a:nobody:nothing:1.0:*:*:*:*:*:*:*"))
    assert data == {"vulnerabilities": [], "totalResults": 0}


# --- the endpoint -----------------------------------------------------------
def test_precise_reports_unmatched_with_a_reason(client):
    """An empty inventory is fine; the contract is that nothing is ever implied."""
    r = client.get("/api/security/precise")
    assert r.status_code == 200
    body = r.json()
    assert body["match_mode"] == "cpe"
    assert body["matched"] == []
    assert body["coverage"]["total"] == 0


def test_precise_separates_mapped_from_unmapped(client, monkeypatch):
    monkeypatch.setitem(cpe.CPE_MAP, "7zip.7zip", cpe.CpeEntry("7-zip", "7-zip"))
    monkeypatch.setitem(cpe.CPE_MAP, "Bad.Version", cpe.CpeEntry("acme", "thing"))
    _seed_inventory(
        client,
        monkeypatch,
        [("7zip.7zip", "26.02"), ("Weird.App", "1.0"), ("Bad.Version", "> 2.0")],
    )

    body = client.get("/api/security/precise").json()
    reasons = {u["product_id"]: u["reason"] for u in body["unmatched"]}
    assert reasons["Weird.App"] == "no_cpe_mapping"
    assert reasons["Bad.Version"] == "version_not_comparable"
    # 7zip is mapped but has no cached NVD result and refresh wasn't requested
    assert reasons["7zip.7zip"] == "not_yet_checked"
    assert body["coverage"]["mapped"] == 2


def test_precise_never_calls_nvd_unless_asked(client, monkeypatch):
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("NVD must not be called without refresh_nvd=true")

    monkeypatch.setattr(cve, "lookup_by_cpe", boom)
    client.get("/api/security/precise")
    assert called is False
