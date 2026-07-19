"""
Regression tests for the language-independent winget upgrade parser.

The old parser matched English column headers and returned zero rows on Arabic
Windows, which then made the caller mark every package as "installed". These
tests lock in the new right-anchored, split-on-2+-spaces behavior.
"""

from __future__ import annotations

from app.services.software_updates import _parse_winget_row, _parse_winget_table

ENGLISH = """
Name                     Id                          Version      Available    Source
-------------------------------------------------------------------------------------
Mozilla Firefox          Mozilla.Firefox             120.0.1      121.0        winget
Visual Studio Code       Microsoft.VisualStudioCode  1.85.0       1.86.0       winget
Some Old App             Vendor.OldApp               1.0          <Unknown>    winget
Store Thing              9WZDNCRFHVN5                1.0.0        2.0.0        msstore

3 upgrades available.
"""

# Localized header + footer, and deliberately MISALIGNED data columns.
ARABIC = """
الاسم                       المعرف                       الإصدار      المتوفر       المصدر
-------------------------------------------------------------------------------------
Mozilla Firefox     Mozilla.Firefox      120.0.1    121.0    winget
Visual Studio Code    Microsoft.VisualStudioCode   1.85.0   1.86.0    winget

يتوفر تحديث لـ 2 من الحزم.
"""

NO_SOURCE = """
Name              Id             Version   Available
----------------------------------------------------
Git               Git.Git        2.40.0    2.44.0
"""


def _ids(packages):
    return {p.package_id for p in packages}


def test_english_table_parses_and_filters_unknown():
    pkgs = _parse_winget_table(ENGLISH)
    assert _ids(pkgs) == {"Mozilla.Firefox", "Microsoft.VisualStudioCode", "9WZDNCRFHVN5"}
    # <Unknown> available version must be dropped (cannot upgrade it).
    assert "Vendor.OldApp" not in _ids(pkgs)
    # msstore source is preserved.
    store = next(p for p in pkgs if p.package_id == "9WZDNCRFHVN5")
    assert store.source == "msstore"


def test_arabic_localized_headers_still_parse():
    """The whole point of the rewrite: Arabic UI must not yield zero rows."""
    pkgs = _parse_winget_table(ARABIC)
    assert _ids(pkgs) == {"Mozilla.Firefox", "Microsoft.VisualStudioCode"}
    ff = next(p for p in pkgs if p.package_id == "Mozilla.Firefox")
    assert ff.current_version == "120.0.1"
    assert ff.available_version == "121.0"


def test_multiword_name_preserved():
    pkgs = _parse_winget_table(ENGLISH)
    vscode = next(p for p in pkgs if p.package_id == "Microsoft.VisualStudioCode")
    assert vscode.name == "Visual Studio Code"


def test_missing_source_column():
    pkgs = _parse_winget_table(NO_SOURCE)
    assert _ids(pkgs) == {"Git.Git"}
    assert pkgs[0].source == "winget"


def test_empty_and_no_updates_output():
    assert _parse_winget_table("") == []
    assert _parse_winget_table("No installed package found matching input criteria.") == []


def test_footer_and_header_rows_rejected():
    # A localized footer line must not be parsed as a package.
    assert _parse_winget_row("يتوفر تحديث لـ 2 من الحزم.") is None
    # A header row (no version digit in the "current" slot) must be rejected.
    assert _parse_winget_row("Name        Id        Version        Available") is None
