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


# --- products discovered through the registry (no stable id) ----------------
def test_registry_products_are_matched_by_name_not_by_msi_guid():
    """Node.js's ARP id embeds the MSI ProductCode, which changes every release, so
    a mapping keyed on it would stop matching after the next update."""
    guid_id = "ARP" + chr(92) + "Machine" + chr(92) + "X64" + chr(92) + "{8E3EF5A2-585E-453B}"
    identity = cpe.resolve(guid_id, "24.16.0", "Node.js")
    assert identity is not None
    assert identity.cpe_name == "cpe:2.3:a:nodejs:node.js:24.16.0:*:*:*:*:*:*:*"
    # …and the same id with a different name must NOT inherit the mapping
    assert cpe.resolve(guid_id, "1.0.0", "Some Other Program") is None


def test_no_arp_id_is_ever_keyed_in_the_curated_map():
    """Guard the rule above: an ARP id in CPE_MAP is a mapping that will rot."""
    for key in cpe.CPE_MAP:
        assert not key.upper().startswith("ARP" + chr(92)), key


def test_localized_product_is_matched_by_id_suffix():
    """The NVIDIA driver's display name is localized (Arabic here), so the rule keys
    on the component suffix of NVIDIA's fixed GUID instead."""
    pid = "ARP" + chr(92) + "Machine" + chr(92) + "X64" + chr(92) + "{B2FE1952-0186}_Display.Driver"
    identity = cpe.resolve(pid, "610.74", "NVIDIA برنامج تشغيل الرسومات 610.74")
    assert identity is not None
    assert identity.cpe_name.startswith("cpe:2.3:a:nvidia:gpu_display_driver:610.74")


def test_fallback_version_is_fitted_to_the_dictionary_scheme():
    """NVD lists UniGetUI as 2026.2.1.0 (4 parts); the install reports 3."""
    identity = cpe.resolve("ARP" + chr(92) + "x" + chr(92) + "{1}", "2026.2.2", "UniGetUI")
    assert identity is not None and identity.version == "2026.2.2.0"


def test_every_fallback_rule_is_well_formed():
    for rule in cpe.FALLBACK_RULES:
        assert rule.kind in {"name", "id_suffix"}, rule
        e = rule.entry
        assert e.vendor == e.vendor.lower() and ":" not in e.vendor, e
        assert e.product == e.product.lower() and ":" not in e.product, e
        assert e.confidence in {"high", "medium"}, e
        assert e.version_parts in (None, 3, 4), e


def test_documented_exclusion_rules_all_carry_a_reason_and_a_sample():
    assert cpe.EXCLUSION_RULES, "the exclusion rule table must not be empty"
    for rule in cpe.EXCLUSION_RULES:
        assert rule.kind in {"name", "id_suffix"}, rule
        assert len(rule.reason) > 25, rule
        assert rule.sample, "every rule needs a real observed sample for the tests"
        if rule.kind == "name":
            assert rule.pattern.startswith("^"), f"anchor the pattern: {rule.pattern}"
        else:
            assert rule.pattern == rule.pattern.lower(), rule


def test_exclusions_survive_a_version_bump():
    """v1.11.0 keyed these on the exact display name, so upgrading this machine broke
    its own entry: 'HomeUpdater 1.10.6' stopped matching 'HomeUpdater 1.11.0' and the
    product reappeared as 'not investigated' in an exported report. Every rule is now
    checked against its real sample AND against a version-bumped variant."""
    for rule in cpe.EXCLUSION_RULES:
        if rule.kind == "id_suffix":
            assert cpe.classify_unmapped(rule.sample, "Whatever 9.9.9") == "documented_exclusion"
            continue
        for name in (rule.sample, f"{rule.sample.rstrip('0123456789. ')} 99.99.99"):
            assert cpe.classify_unmapped("ARP" + chr(92) + "x" + chr(92) + "{g}", name) == (
                "documented_exclusion"
            ), f"{rule.pattern} lost {name!r}"
            assert cpe.exclusion_detail("ARP" + chr(92) + "x" + chr(92) + "{g}", name), name


def test_our_own_app_is_excluded_by_its_pinned_appid_not_its_name():
    """The installer pins AppId across releases; the display name carries the version."""
    for version in ("1.10.6", "1.11.0", "2.0.0"):
        pid = (
            "ARP"
            + chr(92)
            + "Machine"
            + chr(92)
            + "X64"
            + chr(92)
            + "{8F3A1C7E-2B4D-4E6A-9C1F-5D7E8A9B0C1D}_is1"
        )
        assert cpe.classify_unmapped(pid, f"HomeUpdater {version}") == "documented_exclusion"


# --- the honest denominator --------------------------------------------------
def test_coverage_separates_store_packages_from_the_real_gap():
    """Measured reality: most of a Windows 11 inventory is Store/inbox packages whose
    identity version NVD does not track. Reporting one flat percentage read as
    'the map is lazy' when the truth is 'this estate is not CPE-addressable'."""
    store = "MSIX" + chr(92) + "Microsoft.WindowsCalculator_11.2605.9.0_x64__8wekyb3d8bbwe"
    products = [
        ("7zip.7zip", "7-Zip"),
        ("Microsoft.Teams", "Microsoft Teams"),  # documented exclusion
        (store, "الحاسبة في Windows"),
        ("Some.Unknown.Thing", "Unknown Thing"),
    ]
    cov = cpe.coverage(products)
    assert cov["by_reason"] == {
        "mapped": 1,
        "documented_exclusion": 1,
        "store_package": 1,
        "not_investigated": 1,
    }
    assert sum(cov["by_reason"].values()) == cov["total"]
    assert cov["percent"] == 25.0, "the raw percentage must stay the headline"
    assert cov["addressable_total"] == 2 and cov["addressable_percent"] == 50.0


def test_unmatched_reason_is_specific_enough_to_act_on():
    store = "MSIX" + chr(92) + "Microsoft.Paint_11.2605.71.0_x64__8wekyb3d8bbwe"
    assert cpe.unmatched_reason(store, "11.2605.71.0", "الرسام") == "store_package"
    assert cpe.unmatched_reason("Microsoft.Teams", "26183.1", "Teams") == "documented_exclusion"
    assert cpe.unmatched_reason("Nope.Nope", "1.0", "Nope") == "no_cpe_mapping"
    # a product we CAN identify but whose version is unusable is a different problem
    assert cpe.unmatched_reason("7zip.7zip", "Unknown", "7-Zip") == "version_not_comparable"


def test_coverage_still_accepts_a_bare_id_list():
    """Backwards compatible: older callers pass ids only (name rules then can't fire)."""
    cov = cpe.coverage(["7zip.7zip", "Nope.Nope"])
    assert cov["total"] == 2 and cov["mapped"] == 1


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


# --- what may be COUNTED as a finding ---------------------------------------
# Both false positives below were produced by the shipped code on a real machine
# (v1.10.3, 2026-07-25) before this classifier existed.
def _because(**kw) -> dict:
    base = {
        "vulnerable": True,
        "criteria": "cpe:2.3:a:python:python:*:*:*:*:*:*:*:*",
        "start_including": None,
        "start_excluding": None,
        "end_including": None,
        "end_excluding": None,
    }
    return {**base, **kw}


def test_a_bounded_range_is_countable():
    assert cve.classify_applicability(_because(end_excluding="3.15.0"), "3.14.6") == "bounded"


def test_a_non_vulnerable_platform_node_is_not_a_finding():
    """Measured: CVE-2020-29396 (an Odoo flaw) came back for python 3.14.6 because
    NVD lists Python there as the platform, with vulnerable=false."""
    got = cve.classify_applicability(_because(vulnerable=False, start_including="3.6.0"), "3.14.6")
    assert got == "not_vulnerable"


def test_a_date_bound_against_a_normal_version_is_not_comparable():
    """Measured: CVE-2025-25468 bounds FFmpeg at < 2025-01-13; comparing 8.1.2 to a
    date made a 2026 build look affected."""
    got = cve.classify_applicability(_because(end_excluding="2025-01-13"), "8.1.2")
    assert got == "scheme_mismatch"


def test_two_date_versions_are_comparable_to_each_other():
    got = cve.classify_applicability(_because(end_excluding="2025-01-13"), "2024-11-02")
    assert got == "bounded"


def test_no_bounds_at_all_stays_unbounded():
    assert cve.classify_applicability(_because(), "3.14.6") == "unbounded"
    assert cve.classify_applicability(None, "3.14.6") == "unbounded"


def test_counted_and_uncounted_splits_and_labels():
    cves = [
        {"id": "CVE-A", "applies_because": _because(end_excluding="3.15.0")},
        {"id": "CVE-B", "applies_because": _because(vulnerable=False, start_including="3.6.0")},
        {"id": "CVE-C", "applies_because": _because(end_excluding="2025-01-13")},
        {"id": "CVE-D", "applies_because": _because()},
    ]
    counted, uncounted = cve.counted_and_uncounted(cves, "3.14.6")
    assert [c["id"] for c in counted] == ["CVE-A"]
    assert {c["id"]: c["precision"] for c in uncounted} == {
        "CVE-B": "not_vulnerable",
        "CVE-C": "scheme_mismatch",
        "CVE-D": "unbounded",
    }


def test_a_cve_listing_our_product_twice_prefers_the_vulnerable_node():
    """Odoo-shaped advisory: Python appears as a non-vulnerable platform first."""
    data = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2026-0002",
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "vulnerable": False,
                                            "criteria": "cpe:2.3:a:python:python:*:*:*:*:*:*:*:*",
                                            "versionStartIncluding": "3.6.0",
                                        },
                                        {
                                            "vulnerable": True,
                                            "criteria": "cpe:2.3:a:python:python:*:*:*:*:*:*:*:*",
                                            "versionEndExcluding": "3.15.0",
                                        },
                                    ]
                                }
                            ]
                        }
                    ],
                }
            }
        ]
    }
    ranges = cve.matched_ranges(data, "python")
    assert len(ranges) == 1
    assert ranges[0]["vulnerable"] is True
    assert ranges[0]["end_excluding"] == "3.15.0"


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


def test_precise_does_not_count_platform_or_date_bounded_records(client, monkeypatch):
    """The two real false positives, end to end: neither may appear as a finding,
    and both must still be listed with the reason they were set aside."""
    monkeypatch.setitem(cpe.CPE_MAP, "Python.Python.3.14", cpe.CpeEntry("python", "python"))
    _seed_inventory(client, monkeypatch, [("Python.Python.3.14", "3.14.6")])

    def _cve(cid: str, match: dict) -> dict:
        return {
            "cve": {
                "id": cid,
                "published": "2026-01-01T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "x"}],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 8.8, "baseSeverity": "HIGH"}}]
                },
                "configurations": [{"nodes": [{"cpeMatch": [match]}]}],
            }
        }

    PY = "cpe:2.3:a:python:python:*:*:*:*:*:*:*:*"
    response = {
        "totalResults": 3,
        "vulnerabilities": [
            _cve("CVE-REAL", {"vulnerable": True, "criteria": PY, "versionEndExcluding": "3.15.0"}),
            _cve(
                "CVE-PLATFORM",
                {"vulnerable": False, "criteria": PY, "versionStartIncluding": "3.6.0"},
            ),
            _cve(
                "CVE-DATED",
                {"vulnerable": True, "criteria": PY, "versionEndExcluding": "2025-01-13"},
            ),
        ],
    }

    async def fake_fetch(cpe_name, results_per_page=50):
        return response

    monkeypatch.setattr(cve, "fetch_by_cpe", fake_fetch)
    found = client.get("/api/security/precise?refresh_nvd=true").json()["matched"][0]

    assert [c["id"] for c in found["cves"]] == ["CVE-REAL"]
    assert {c["id"]: c["precision"] for c in found["broad_matches"]} == {
        "CVE-PLATFORM": "not_vulnerable",
        "CVE-DATED": "scheme_mismatch",
    }

    # The pack a customer pays for must report the SAME single finding.
    pack = client.get("/api/evidence/preview").json()
    assert pack["findings_total"] == 1
    assert pack["broad_matches_total"] == 2


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
    # ``examined`` joined the contract when the fetch started paging: a caller has to
    # be able to tell "NVD has nothing" from "we only read part of what NVD has".
    assert data == {"vulnerabilities": [], "totalResults": 0, "examined": 0}


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
