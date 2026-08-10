"""The sold document must not claim more than it examined.

Three defects were found by exercising the real product against live NVD, and all three
were invisible on the face of the artifact — which is the worst place for a defect in a
product whose entire thesis is that the wording IS the deliverable:

* the pack printed "Findings (48)" where NVD had answered 4,494, because the fetch read
  the OLDEST 50 records and NVD paginates by CVE id, not by severity;
* a pack built from a 400-day-old cache printed byte-identically to a fresh one, with
  today's date on the cover;
* on a machine where nothing had ever been checked it printed a coverage percentage
  above an empty findings table, which reads as "we looked, you are clean".

These tests fail if any of them comes back.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.orm import Base, CVECacheORM, InstalledSoftwareORM
from app.services import cve, evidence


async def _db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _software(db, product_id: str, name: str, version: str) -> None:
    db.add(InstalledSoftwareORM(device_id=0, product_id=product_id, name=name, version=version))


def _cache(db, cpe_name: str, cves: list, total: int, examined: int, when: datetime) -> None:
    db.add(
        CVECacheORM(
            keyword=cpe_name,
            total_results=total,
            examined=examined,
            data=json.dumps(cves, ensure_ascii=False),
            fetched_at=when,
        )
    )


# --- the cap must be stated ----------------------------------------------------------
def test_a_partial_reading_of_nvd_is_named_product_by_product():
    """Measured on the real product: Chrome 90 has 3,391 advisories and the pack showed
    eight, drawn from the oldest fifty, with nothing on the page saying so."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "Google.Chrome", "Google Chrome", "90.0.4430.72")
            await db.commit()
            from app.services import cpe as cpe_mod

            identity = cpe_mod.resolve("Google.Chrome", "90.0.4430.72", "Google Chrome")
            if identity is None:
                pytest.skip("this build maps Chrome differently")
            _cache(db, identity.cpe_name, [], 3391, 2000, datetime.now(UTC))
            await db.commit()

            pack = await evidence.build(db, licensee="Acme")
            ev = pack["pack"]["evidence_state"]
            assert ev["nvd_records_total"] == 3391
            assert ev["nvd_records_examined"] == 2000
            assert ev["capped_products"], "a partial reading must be named, not implied"

            html = evidence.to_html(pack)
            assert "2000" in html and "3391" in html
            assert "Not every NVD record was examined" in html
        await engine.dispose()

    asyncio.run(run())


def test_a_complete_reading_says_nothing_extra():
    """The warning must not cry wolf: when everything was read, no banner."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            from app.services import cpe as cpe_mod

            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            identity = cpe_mod.resolve("7zip.7zip", "21.07", "7-Zip")
            if identity is None:
                pytest.skip("this build maps 7-Zip differently")
            _cache(db, identity.cpe_name, [], 17, 17, datetime.now(UTC))
            await db.commit()
            pack = await evidence.build(db, licensee="Acme")
            assert pack["pack"]["evidence_state"]["capped_products"] == []
            assert "Not every NVD record was examined" not in evidence.to_html(pack)
        await engine.dispose()

    asyncio.run(run())


# --- the evidence must carry its own date --------------------------------------------
def test_the_pack_prints_when_the_vulnerability_data_was_fetched():
    async def run():
        engine, Session = await _db()
        async with Session() as db:
            from app.services import cpe as cpe_mod

            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            identity = cpe_mod.resolve("7zip.7zip", "21.07", "7-Zip")
            if identity is None:
                pytest.skip("this build maps 7-Zip differently")
            old = datetime.now(UTC) - timedelta(days=400)
            _cache(db, identity.cpe_name, [], 17, 17, old)
            await db.commit()

            pack = await evidence.build(db, licensee="Acme")
            stamp_date = old.date().isoformat()
            assert pack["pack"]["evidence_state"]["newest_checked_at"].startswith(stamp_date)
            html = evidence.to_html(pack)
            assert stamp_date in html, "a 400-day-old pack used to print like a fresh one"
        await engine.dispose()

    asyncio.run(run())


# --- never checked is not the same as nothing found ----------------------------------
def test_a_machine_that_was_never_checked_is_told_so_in_bold():
    """The single sentence in this document that could cost someone money."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "7zip.7zip", "7-Zip", "21.07")
            _software(db, "Google.Chrome", "Google Chrome", "90.0.4430.72")
            await db.commit()

            pack = await evidence.build(db, licensee="Acme")
            body = pack["pack"]
            assert body["findings_total"] == 0
            assert body["evidence_state"]["never_checked"] is True
            html = evidence.to_html(pack)
            assert "has not run" in html, "silence here reads as 'your machine is clean'"
        await engine.dispose()

    asyncio.run(run())


# --- the CSV is a document, not an anonymous table ------------------------------------
def test_a_product_name_cannot_execute_in_a_spreadsheet():
    """Names come from the Windows registry and the file is served with a BOM so Excel
    opens it on double-click. A name beginning with = is a formula unless neutralized."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "=cmd|'/c calc'!A1", "=cmd|'/c calc'!A1", "1.0")
            await db.commit()
            pack = await evidence.build(db, licensee="Acme")
            text = evidence.to_csv(pack)
        await engine.dispose()
        return text

    text = asyncio.run(run())
    rows = list(csv.reader(io.StringIO(text)))
    data_rows = [r for r in rows if r and not r[0].startswith("#") and r[0] != "product_id"]
    assert data_rows, "the product must still appear"
    for row in data_rows:
        for cell in row:
            assert not cell.startswith(("=", "+", "@")), f"formula reaches the sheet: {cell!r}"
    assert "'=cmd" in text, "neutralized, not deleted — the auditor still reads the name"


def test_the_csv_identifies_itself():
    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            pack = await evidence.build(db, licensee="Acme Ltd")
            return evidence.to_csv(pack), pack["content_sha256"]

    text, stamp = asyncio.run(run())
    assert "Acme Ltd" in text, "no licensee = an anonymous table"
    assert stamp in text, "no stamp = nothing ties it to the pack"
    assert "generated_at" in text
    assert "vulnerability_data_fetched" in text


def test_the_unmatched_rows_carry_the_readable_name():
    """The auditor used to get MSIX\\Microsoft.WindowsCalculator_11.2605… where the HTML
    said "Calculator" — the exact failure evidence.py's own docstring forbids."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(
                db,
                "MSIX\\Microsoft.WindowsCalculator_11.2605.9.0_x64__8wekyb3d8bbwe",
                "Calculator",
                "11.2605.9.0",
            )
            await db.commit()
            pack = await evidence.build(db, licensee="Acme")
            return evidence.to_csv(pack)

    text = asyncio.run(run())
    body = [line for line in text.splitlines() if line.startswith("MSIX")]
    assert body, "the row must exist"
    assert "Calculator" in body[0], "the name column was blank"


# --- what the stamp actually covers ---------------------------------------------------
def test_the_stamp_sentence_says_which_file_it_covers():
    """The old sentence — "a SHA-256 over this report's own content" — was untrue of the
    page it was printed on: the hash covers the JSON body, so a reader holding only the
    printed report could verify nothing."""
    assert "JSON" in evidence.COPY["stamp_en"]
    assert "not over this page" in evidence.COPY["stamp_en"]
    assert "JSON" in evidence.COPY["stamp_ar"]


def test_the_stamp_still_verifies_the_json_it_claims_to_cover():
    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            return await evidence.build(db, licensee="Acme")

    pack = asyncio.run(run())
    import hashlib

    recomputed = hashlib.sha256(evidence._canonical(pack["pack"]).encode("utf-8")).hexdigest()
    assert recomputed == pack["content_sha256"]


# --- the fetch reads more than one page ----------------------------------------------
def test_the_fetch_pages_until_nvd_is_exhausted(monkeypatch):
    """One short page meant ranking a product by its oldest advisories."""
    pages = []

    class _Resp:
        status_code = 200

        def __init__(self, start):
            self.start = start

        def raise_for_status(self):
            pass

        def json(self):
            remaining = max(0, 3391 - self.start)
            count = min(2000, remaining)
            block = [{"cve": {"id": f"CVE-X-{self.start + i}"}} for i in range(count)]
            return {"vulnerabilities": block, "totalResults": 3391}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url, params=None, headers=None):
            pages.append(params["startIndex"])
            return _Resp(params["startIndex"])

    monkeypatch.setattr(cve.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(cve, "NVD_PAGE_PAUSE_SECONDS", 0.0)
    data = asyncio.run(cve.fetch_by_cpe("cpe:2.3:a:google:chrome:90.0.4430.72:*:*:*:*:*:*:*"))
    assert pages == [0, 2000], "it must ask for the second page"
    assert data["totalResults"] == 3391
    assert data["examined"] == 3391, "the whole answer, not the oldest page"


# --- residuals the verification pass found in the FIX itself --------------------------
def test_a_cache_that_never_recorded_its_coverage_is_still_disclosed():
    """The guard read `if total and examined and examined < total`, so `examined == 0`
    — every row cached before the paging fix — was skipped. Measured on the real
    database: all 25 CPE rows had examined=0, so the pack said "0 of 15 examined" and
    named nothing. "We do not know how much of NVD was read" is the case that most
    needs saying, not the one to hide."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            from app.services import cpe as cpe_mod

            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            identity = cpe_mod.resolve("7zip.7zip", "21.07", "7-Zip")
            if identity is None:
                pytest.skip("this build maps 7-Zip differently")
            _cache(db, identity.cpe_name, [], 17, 0, datetime.now(UTC))  # legacy row
            await db.commit()
            pack = await evidence.build(db, licensee="Acme")
            assert pack["pack"]["evidence_state"]["capped_products"], "a legacy row must be named"
            assert "Not every NVD record was examined" in evidence.to_html(pack)
        await engine.dispose()

    asyncio.run(run())


def test_the_caveat_is_read_before_the_percentage():
    """A reader meeting '100.0% of addressable' before the disclaimer has already formed
    the belief the disclaimer exists to prevent."""

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            return evidence.to_html(await evidence.build(db, licensee="Acme"))

    html = asyncio.run(run())
    assert html.index("Vulnerability evidence") < html.index("Coverage")


def test_the_stamp_covers_exactly_what_the_reader_is_told_to_hash():
    """The document says: hash the JSON file and compare. That has to be true of the
    file the product hands over — three different byte sequences were in play."""
    import hashlib

    from app.services import audit as audit_mod

    async def run():
        engine, Session = await _db()
        async with Session() as db:
            _software(db, "7zip.7zip", "7-Zip", "21.07")
            await db.commit()
            return await evidence.build(db, licensee="Acme")

    pack = asyncio.run(run())
    served = audit_mod.canonical(pack["pack"]).encode("utf-8")  # what /pack.json returns
    assert hashlib.sha256(served).hexdigest() == pack["content_sha256"]
    # And the envelope-with-indent form, which the UI used to download, does NOT match —
    # that is the whole reason this test exists.
    import json as _json

    envelope = _json.dumps(pack, indent=2, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(envelope).hexdigest() != pack["content_sha256"]
