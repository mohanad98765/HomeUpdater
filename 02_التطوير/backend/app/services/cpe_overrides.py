"""Site-provided CPE mappings — how the curated table grows without a new release.

Why this exists: ``cpe.CPE_MAP`` can only ever cover software we have seen. A clinic
running a practice-management suite, or an office running an accounting package, would
otherwise get zero coverage for the software that matters most to them, and would have
to wait for a release to get any.

The discipline of the built-in table is preserved, not relaxed:

* every override carries **evidence**: who verified it, when, and what NVD's CPE
  dictionary actually returned. A mapping with no evidence is refused at load time —
  the whole product rests on findings being defensible.
* an override is **labelled in the report**. Its confidence is capped at ``medium`` and
  its source is ``site``, so a reader of the evidence pack can tell a vendor-verified
  mapping from one the customer added. Silently blending them would let a customer's
  guess appear with our authority.
* a malformed file **never** breaks the app or silently disables coverage: it is
  skipped with a logged reason, and the built-in table keeps working.
* an override may not replace a documented exclusion. Those entries exist because a
  plausible-looking CPE is WRONG (``microsoft:windows_app`` is the Remote Desktop
  client, not the App SDK); letting a file re-add them would resurrect exactly the
  false findings the exclusion was written to prevent.

File: ``%APPDATA%/HomeUpdater/data/cpe_overrides.json``

    {
      "version": 1,
      "mappings": [
        {
          "product_id": "Acme.PracticeSuite",       # winget id, or…
          "name_pattern": "^Acme Practice Suite",    # …an anchored display-name regex
          "vendor": "acme",
          "product": "practice_suite",
          "version_parts": 3,
          "verified_by": "IT — Ahmed",
          "verified_on": "2026-07-26",
          "evidence": "cpe:2.3:a:acme:practice_suite lists 3.1.0 … 4.2.2 (18 entries)"
        }
      ]
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..config import get_data_dir

FILENAME = "cpe_overrides.json"
# Evidence has to be a real sentence about what NVD holds, not "ok" — the field is the
# only thing standing between a curated table and a wishlist.
_MIN_EVIDENCE = 25


@dataclass(frozen=True)
class Override:
    """One site-provided mapping. ``source='site'`` travels into the report."""

    product_id: str
    name_pattern: str
    vendor: str
    product: str
    version_parts: int | None
    verified_by: str
    verified_on: str
    evidence: str

    @property
    def caveat(self) -> str:
        return (
            f"site-provided mapping, verified by {self.verified_by} on {self.verified_on}"
            f" — {self.evidence}"
        )


def path() -> Path:
    return get_data_dir() / FILENAME


def _valid_component(value: str) -> bool:
    """CPE vendor/product components: lowercase, no colons, no spaces."""
    return bool(value) and value == value.lower() and ":" not in value and " " not in value


def _parse_one(raw: dict, index: int, blocked: set[str]) -> Override | None:
    def bad(why: str) -> None:
        logger.warning(f"{FILENAME}: mapping #{index} ignored — {why}")

    if not isinstance(raw, dict):
        bad("not an object")
        return None
    product_id = str(raw.get("product_id") or "").strip()
    name_pattern = str(raw.get("name_pattern") or "").strip()
    if not product_id and not name_pattern:
        bad("needs product_id or name_pattern")
        return None
    if product_id and product_id in blocked:
        bad(f"{product_id} is a documented exclusion and must not be re-mapped")
        return None
    vendor = str(raw.get("vendor") or "").strip()
    product = str(raw.get("product") or "").strip()
    if not _valid_component(vendor) or not _valid_component(product):
        bad("vendor/product must be lowercase CPE components")
        return None
    verified_by = str(raw.get("verified_by") or "").strip()
    verified_on = str(raw.get("verified_on") or "").strip()
    evidence = str(raw.get("evidence") or "").strip()
    if not verified_by or not verified_on:
        bad("verified_by and verified_on are required")
        return None
    if len(evidence) < _MIN_EVIDENCE:
        bad(f"evidence must say what NVD returned (at least {_MIN_EVIDENCE} chars)")
        return None
    parts = raw.get("version_parts")
    if parts is not None and parts not in (3, 4):
        bad("version_parts must be 3, 4, or absent")
        return None
    if name_pattern:
        if not name_pattern.startswith("^"):
            bad("name_pattern must be anchored with ^ so it cannot match half the estate")
            return None
        try:
            re.compile(name_pattern)
        except re.error as exc:
            bad(f"name_pattern is not a valid regex: {exc}")
            return None
    return Override(
        product_id=product_id,
        name_pattern=name_pattern,
        vendor=vendor,
        product=product,
        version_parts=parts,
        verified_by=verified_by,
        verified_on=verified_on,
        evidence=evidence,
    )


def load(blocked: set[str] | None = None) -> list[Override]:
    """Read the override file. Never raises: a bad file logs and yields nothing."""
    file = path()
    if not file.exists():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a broken file must not break the app
        logger.warning(f"{FILENAME}: unreadable, ignoring it ({exc})")
        return []
    if not isinstance(data, dict) or data.get("version") != 1:
        logger.warning(f"{FILENAME}: missing or unsupported 'version': 1")
        return []
    raw_list = data.get("mappings")
    if not isinstance(raw_list, list):
        logger.warning(f"{FILENAME}: 'mappings' must be a list")
        return []
    out: list[Override] = []
    for i, raw in enumerate(raw_list, 1):
        parsed = _parse_one(raw, i, blocked or set())
        if parsed:
            out.append(parsed)
    if out:
        logger.info(f"{FILENAME}: {len(out)} site mapping(s) loaded")
    return out
