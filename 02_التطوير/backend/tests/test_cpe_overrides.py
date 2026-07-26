"""Site-provided CPE mappings — the table has to grow without a release, but the
growth must not be able to launder a guess into a paid report.

Every test here is about that boundary: evidence is mandatory, a documented exclusion
cannot be re-mapped, a shipped mapping always wins, the site origin is visible in the
output, and a broken file degrades to "no overrides" instead of taking the app down.
"""

from __future__ import annotations

import json

import pytest

from app.services import cpe, cpe_overrides

GOOD = {
    "product_id": "Acme.PracticeSuite",
    "vendor": "acme",
    "product": "practice_suite",
    "version_parts": 3,
    "verified_by": "IT — Ahmed",
    "verified_on": "2026-07-26",
    "evidence": "cpe:2.3:a:acme:practice_suite lists 3.1.0 through 4.2.2 (18 entries)",
}


def write(tmp_path, mappings, version=1):
    """Point the loader at a temp data dir and write a file into it."""
    body = {"version": version, "mappings": mappings}
    (tmp_path / cpe_overrides.FILENAME).write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cpe_overrides, "get_data_dir", lambda: tmp_path)
    return tmp_path


# --- loading ----------------------------------------------------------------
def test_no_file_means_no_overrides(data_dir):
    assert cpe_overrides.load() == []


def test_a_well_formed_mapping_loads(data_dir):
    write(data_dir, [GOOD])
    (ov,) = cpe_overrides.load()
    assert (ov.vendor, ov.product, ov.version_parts) == ("acme", "practice_suite", 3)
    assert "Ahmed" in ov.caveat and "2026-07-26" in ov.caveat


def test_a_corrupt_file_is_ignored_not_fatal(data_dir):
    (data_dir / cpe_overrides.FILENAME).write_text("{not json", encoding="utf-8")
    assert cpe_overrides.load() == []


def test_unsupported_version_is_ignored(data_dir):
    write(data_dir, [GOOD], version=99)
    assert cpe_overrides.load() == []


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": "ok"},  # evidence must state what NVD returned
        {"evidence": ""},
        {"verified_by": ""},
        {"verified_on": ""},
        {"vendor": "Acme"},  # CPE components are lowercase
        {"product": "practice suite"},  # …and have no spaces
        {"vendor": "acme:corp"},
        {"version_parts": 2},  # only 3, 4 or absent
        {"product_id": "", "name_pattern": ""},  # needs one of the two
        {"product_id": "", "name_pattern": "Acme"},  # pattern must be anchored
        {"product_id": "", "name_pattern": "^(unclosed"},  # …and compile
    ],
)
def test_mappings_without_the_required_evidence_are_refused(data_dir, change):
    write(data_dir, [{**GOOD, **change}])
    assert cpe_overrides.load() == [], f"accepted a bad mapping: {change}"


def test_one_bad_mapping_does_not_discard_the_good_ones(data_dir):
    write(data_dir, [{**GOOD, "evidence": "no"}, {**GOOD, "product_id": "Other.App"}])
    loaded = cpe_overrides.load()
    assert [o.product_id for o in loaded] == ["Other.App"]


def test_a_documented_exclusion_cannot_be_re_mapped(data_dir):
    """Those entries exist because a plausible CPE is WRONG; a file must not undo it."""
    write(data_dir, [{**GOOD, "product_id": "Microsoft.Teams"}])
    assert cpe_overrides.load(blocked=set(cpe.UNMAPPABLE)) == []


# --- how resolution treats them ---------------------------------------------
def test_an_override_resolves_and_is_labelled_site(data_dir):
    write(data_dir, [GOOD])
    identity = cpe.resolve("Acme.PracticeSuite", "4.2", "Acme Practice Suite")
    assert identity is not None
    assert identity.cpe_name == "cpe:2.3:a:acme:practice_suite:4.2.0:*:*:*:*:*:*:*"
    entry = cpe.entry_for("Acme.PracticeSuite", "Acme Practice Suite")
    assert entry is not None
    assert entry.source == "site", "the report must be able to say who verified it"
    assert entry.confidence == "medium", "a site mapping is never presented as high"
    assert "verified by IT — Ahmed" in entry.caveat


def test_an_override_can_match_on_the_display_name(data_dir):
    write(data_dir, [{**GOOD, "product_id": "", "name_pattern": "^Acme Practice Suite"}])
    guid_id = "ARP" + chr(92) + "Machine" + chr(92) + "X64" + chr(92) + "{1234}"
    assert cpe.resolve(guid_id, "4.2.0", "Acme Practice Suite 4.2") is not None
    assert cpe.resolve(guid_id, "4.2.0", "Something Else") is None


def test_a_shipped_mapping_always_wins_over_a_site_file(data_dir):
    """A customer file must not be able to silently redirect a mapping we verified."""
    write(data_dir, [{**GOOD, "product_id": "7zip.7zip", "vendor": "evil", "product": "thing"}])
    identity = cpe.resolve("7zip.7zip", "26.02", "7-Zip")
    assert identity is not None
    assert identity.vendor == "7-zip", "the shipped entry must take precedence"


def test_overrides_count_as_covered_and_close_the_gap(data_dir):
    before = cpe.coverage([("Acme.PracticeSuite", "Acme Practice Suite")])
    assert before["by_reason"]["not_investigated"] == 1
    write(data_dir, [GOOD])
    after = cpe.coverage([("Acme.PracticeSuite", "Acme Practice Suite")])
    assert after["mapped"] == 1 and after["percent"] == 100.0
    assert after["by_reason"]["not_investigated"] == 0
