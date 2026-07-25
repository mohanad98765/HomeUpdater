"""Partner roll-up — aggregating site packs without laundering tampered ones.

The point of these tests: an aggregate that silently averages an edited pack is
worse than no aggregate, because it gives a forged input the credibility of a
total. So a tampered pack must be REJECTED, visibly, and excluded from every number.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import audit, licensing, rollup

CSRF = {"X-HomeUpdater": "1"}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def vendor(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        licensing, "VENDOR_PUBLIC_KEY_HEX", priv.public_key().public_bytes_raw().hex()
    )

    def make(tier="partner", licensee="MSP Co"):
        payload = {
            "licensee": licensee,
            "tier": tier,
            "devices_max": licensing.TIER_DEVICE_LIMIT.get(tier, 0),
            "expires": (date.today() + timedelta(days=365)).isoformat(),
            "issued_at": datetime.now(UTC).date().isoformat(),
            "key_id": "k1",
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"HU1.{_b64(raw)}.{_b64(priv.sign(raw))}"

    return make


@pytest.fixture(autouse=True)
def _clean():
    licensing.clear()
    yield
    licensing.clear()


def make_pack(
    *, site="Clinic A", devices=10, coverage=50.0, mapped=5, findings=2, chain_ok=True, broad=1
) -> dict:
    """A pack shaped like a real export, correctly stamped."""
    body = {
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": "1.9.0",
        "licensee": site,
        "inventory_total": devices,
        "coverage": {
            "total": devices,
            "mapped": mapped,
            "unmapped": devices - mapped,
            "percent": coverage,
        },
        "matched": [],
        "unmatched": [{"product_id": "X.Y", "version": "1", "reason": "no_cpe_mapping"}],
        "findings_total": findings,
        "broad_matches_total": broad,
        "updates_applied": [],
        "audit": {
            "chain_ok": chain_ok,
            "entries": 12,
            "broken_at": None if chain_ok else 7,
            "reason": "" if chain_ok else "edited",
            "head_seq": 12,
            "head_hash": "a" * 64,
        },
        "copy": {},
    }
    stamp = hashlib.sha256(audit.canonical(body).encode("utf-8")).hexdigest()
    return {"pack": body, "content_sha256": stamp, "stamp_kind": "sha256-content-hash"}


# --- verification -----------------------------------------------------------
def test_a_correctly_stamped_pack_verifies():
    ok, reason = rollup.verify_pack(make_pack())
    assert ok is True and reason == ""


def test_an_edited_pack_fails_verification():
    """The realistic fraud: lower your finding count before sending it to the MSP."""
    pack = make_pack(findings=9)
    pack["pack"]["findings_total"] = 0  # stamp left untouched
    ok, reason = rollup.verify_pack(pack)
    assert ok is False and reason == "stamp_mismatch"


def test_a_restamped_pack_verifies_but_that_is_expected():
    """Honest boundary: the stamp proves the copy matches what was issued, not who
    issued it. Re-stamping an edited body passes — a signature would be needed to
    stop that, and the product never claims one."""
    pack = make_pack(findings=9)
    pack["pack"]["findings_total"] = 0
    pack["content_sha256"] = hashlib.sha256(
        audit.canonical(pack["pack"]).encode("utf-8")
    ).hexdigest()
    ok, _ = rollup.verify_pack(pack)
    assert ok is True


@pytest.mark.parametrize(
    "junk",
    [None, {}, {"pack": {}}, {"content_sha256": "x"}, {"pack": "no", "content_sha256": "x"}, 42],
)
def test_malformed_input_is_rejected_not_crashed(junk):
    ok, reason = rollup.verify_pack(junk)
    assert ok is False and reason


# --- aggregation ------------------------------------------------------------
def test_totals_only_count_verified_sites():
    good_a = make_pack(site="A", devices=10, coverage=40.0, findings=3)
    good_b = make_pack(site="B", devices=20, coverage=60.0, findings=1)
    bad = make_pack(site="C", devices=100, coverage=100.0, findings=99)
    bad["pack"]["findings_total"] = 0  # tampered

    result = rollup.build([good_a, good_b, bad])
    t = result["totals"]
    assert t["sites_verified"] == 2
    assert t["sites_rejected"] == 1
    assert t["products"] == 30, "the tampered site's 100 products must not be counted"
    assert t["findings"] == 4
    assert t["avg_coverage_percent"] == 50.0
    assert result["rejected"][0]["reason"] == "stamp_mismatch"


def test_broken_chain_sites_sort_first():
    ok_site = make_pack(site="OK", findings=99)
    broken = make_pack(site="Broken", findings=0, chain_ok=False)
    result = rollup.build([ok_site, broken])
    assert result["sites"][0]["site"] == "Broken", "an invalid report outranks bad news"
    assert result["totals"]["sites_with_broken_chain"] == 1


def test_the_same_pack_twice_is_counted_once():
    """Dragging a folder in twice must not double the numbers a partner reports."""
    pack = make_pack(site="Clinic A", devices=10, findings=3)
    result = rollup.build([pack, pack])
    t = result["totals"]
    assert t["sites_verified"] == 1
    assert t["products"] == 10, "one machine's 10 products must not become 20"
    assert t["findings"] == 3
    assert t["sites_rejected"] == 1
    assert result["rejected"][0]["reason"] == "duplicate"


def test_two_sites_with_the_same_numbers_are_both_counted():
    """Dedup keys on the stamp, so two genuinely different sites still both count."""
    a = make_pack(site="Clinic A", devices=10, findings=3)
    b = make_pack(site="Clinic B", devices=10, findings=3)
    assert a["content_sha256"] != b["content_sha256"]
    t = rollup.build([a, b])["totals"]
    assert t["sites_verified"] == 2 and t["products"] == 20 and t["sites_rejected"] == 0


def test_csv_header_says_products_not_devices():
    """A pack covers ONE machine; the column counts its software, not machines."""
    header = rollup.to_csv(rollup.build([make_pack()])).splitlines()[0]
    assert "products" in header
    assert "devices" not in header


def test_empty_input_is_safe():
    result = rollup.build([])
    assert result["totals"]["sites_verified"] == 0
    assert result["totals"]["avg_coverage_percent"] == 0.0


def test_site_falls_back_to_a_positional_name():
    pack = make_pack(site="")
    result = rollup.build([pack])
    assert result["sites"][0]["site"] == "site-1"


def test_csv_lists_rejected_packs_too():
    """A partner must SEE an exclusion, not receive a quietly shorter list."""
    bad = make_pack(site="Bad")
    bad["pack"]["findings_total"] = 123
    csv_text = rollup.to_csv(rollup.build([make_pack(site="Good"), bad]))
    assert "Good" in csv_text
    assert "REJECTED" in csv_text
    assert "stamp_mismatch" in csv_text


def test_csv_marks_a_broken_chain_loudly():
    csv_text = rollup.to_csv(rollup.build([make_pack(chain_ok=False)]))
    assert ",NO," in csv_text


# --- endpoint + tier gate ---------------------------------------------------
def test_rollup_requires_a_license(client):
    r = client.post("/api/evidence/rollup", json={"packs": []}, headers=CSRF)
    assert r.status_code == 402


def test_rollup_requires_partner_tier_specifically(client, vendor):
    """A single-site paid tier must not unlock the multi-site product."""
    client.post(
        "/api/evidence/license/activate", json={"key": vendor(tier="evidence25")}, headers=CSRF
    )
    r = client.post("/api/evidence/rollup", json={"packs": []}, headers=CSRF)
    assert r.status_code == 402
    assert r.json()["detail"] == "partner_tier_required"


def test_partner_can_roll_up_and_export_csv(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    packs = [make_pack(site="Clinic A", findings=2), make_pack(site="Law Office", findings=0)]

    r = client.post("/api/evidence/rollup", json={"packs": packs}, headers=CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["sites_verified"] == 2
    assert body["totals"]["sites_with_findings"] == 1

    c = client.post("/api/evidence/rollup.csv", json={"packs": packs}, headers=CSRF)
    assert c.status_code == 200
    assert "Clinic A" in c.text and "Law Office" in c.text


def test_rollup_is_audited(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    client.post("/api/evidence/rollup", json={"packs": [make_pack()]}, headers=CSRF)
    kinds = [e["kind"] for e in client.get("/api/audit/events").json()["events"]]
    assert "rollup_build" in kinds
    assert client.get("/api/audit/verify").json()["ok"] is True
