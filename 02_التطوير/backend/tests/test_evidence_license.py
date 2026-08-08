"""Licensing + the Evidence Pack — the paid artifact and its gate.

The tests that matter here are the ones that try to get the artifact WITHOUT paying
and to forge a key: an entitlement check that can be talked past is worse than none,
because it would be sold as if it worked. The pack's own tests pin the wording
claims too (hash-stamp, not signature) since the wording is the product.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import cpe, evidence, licensing

CSRF = {"X-HomeUpdater": "1"}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def vendor(monkeypatch):
    """A throwaway signing key, with its public half patched into the app — so the
    real vendor private key is never needed (or present) in the test suite."""
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY_HEX", pub_hex)

    def make(tier="evidence25", licensee="Test Clinic", days=365, **extra):
        payload = {
            "licensee": licensee,
            "tier": tier,
            "devices_max": licensing.TIER_DEVICE_LIMIT.get(tier, 0),
            # UTC, because the checker compares against datetime.now(UTC).date(). Using
            # the LOCAL date here made this suite fail for three hours every night in
            # UTC+3 and never once in CI, which runs in UTC — a test that can only fail
            # on a developer's machine.
            "expires": (
                ""
                if days is None
                else (datetime.now(UTC).date() + timedelta(days=days)).isoformat()
            ),
            "issued_at": datetime.now(UTC).date().isoformat(),
            "key_id": "abc123",
            **extra,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"HU1.{_b64(raw)}.{_b64(priv.sign(raw))}"

    return make


@pytest.fixture(autouse=True)
def _clean_license():
    licensing.clear()
    yield
    licensing.clear()


# --- key verification -------------------------------------------------------
def test_valid_key_parses(vendor):
    lic = licensing.parse(vendor())
    assert lic.valid is True and lic.tier == "evidence25"
    assert lic.to_dict()["can_export_evidence"] is True


def test_a_forged_key_is_rejected(vendor):
    """Signed with a DIFFERENT key: the whole point of shipping only the public half."""
    other = Ed25519PrivateKey.generate()
    payload = json.dumps({"tier": "partner", "licensee": "Pirate"}, sort_keys=True).encode()
    forged = f"HU1.{_b64(payload)}.{_b64(other.sign(payload))}"
    lic = licensing.parse(forged)
    assert lic.valid is False
    assert lic.reason == "bad_signature"


def test_editing_the_payload_invalidates_the_key(vendor):
    """Upgrading your own tier by hand must break the signature."""
    good = vendor(tier="evidence25")
    prefix, payload_b64, sig = good.split(".")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    payload["tier"] = "partner"
    edited = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    tampered = f"{prefix}.{_b64(edited)}.{sig}"
    assert licensing.parse(tampered).reason == "bad_signature"


def test_expired_key_is_valid_but_not_entitled(vendor):
    lic = licensing.parse(vendor(days=-1))
    assert lic.valid is True, "the signature is genuine"
    d = lic.to_dict()
    assert d["expired"] is True
    assert d["can_export_evidence"] is False, "an expired key must not entitle"


def test_unparseable_expiry_is_treated_as_expired(vendor):
    lic = licensing.parse(vendor(days=365, expires="not-a-date"))
    assert lic.expired is True, "a broken expiry must fail closed, not become perpetual"


def test_unknown_tier_is_rejected(vendor):
    assert licensing.parse(vendor(tier="enterprise-unlimited")).valid is False


def test_free_tier_does_not_entitle_export(vendor):
    assert licensing.parse(vendor(tier="free")).to_dict()["can_export_evidence"] is False


@pytest.mark.parametrize(
    "junk", ["", "   ", "nonsense", "HU1.only-two-parts", "HU2.a.b", "HU1..", "HU1.@@@.@@@"]
)
def test_garbage_never_validates(junk):
    lic = licensing.parse(junk)
    assert lic.valid is False and lic.to_dict()["can_export_evidence"] is False


def test_invalid_key_is_never_stored(vendor):
    with pytest.raises(licensing.LicenseError):
        licensing.save("HU1.junk.junk")
    assert licensing.load().reason == "none", "nothing must have been written"


def test_stored_key_is_reverified_on_read(vendor, monkeypatch):
    """A key valid under one vendor key must stop working if the app's key changes —
    i.e. the file on disk is never trusted by itself."""
    licensing.save(vendor())
    assert licensing.load().valid is True
    other = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        licensing, "VENDOR_PUBLIC_KEY_HEX", other.public_key().public_bytes_raw().hex()
    )
    assert licensing.load().valid is False


# --- endpoints: the gate ----------------------------------------------------
def test_pack_is_refused_without_a_license(client):
    for path in ("/api/evidence/pack", "/api/evidence/pack.csv", "/api/evidence/pack.html"):
        r = client.get(path)
        assert r.status_code == 402, f"{path} must require payment"


# --- the printable document -------------------------------------------------
def test_printable_document_carries_the_numbers_and_the_limits(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    r = client.get("/api/evidence/pack.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    doc = r.text
    assert doc.lstrip().startswith("<!doctype html>")
    assert 'dir="rtl"' in doc, "the Arabic document must be right-to-left"
    # the honesty clauses have to survive into the document a customer prints
    assert "ليست توقيعًا رقميًّا" in doc
    assert "ليس شهادة اعتماد" in doc
    assert "يَكشِف التلاعب ولا يمنعه" in doc
    # and the numbers that make it auditable
    assert "SHA-256:" in doc
    for heading in ("التغطية", "التحديثات المُطبَّقة", "غير مطابَق مع السبب"):
        assert heading in doc, heading
    assert "window.print()" in doc, "the document must offer to print itself"


def test_printable_document_escapes_product_names(client, vendor, monkeypatch):
    """Product names come from the machine's registry, and this file is opened in a
    browser by the person we are trying to convince — an unescaped name would run."""
    from app.services import software_updates as sw

    async def fake_list():
        return [
            sw.InstalledSoftwareInfo("Evil.App", "<script>alert('x')</script>", "1.0"),
        ], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    client.post("/api/updates/inventory/refresh", headers=CSRF)
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    doc = client.get("/api/evidence/pack.html").text
    assert "<script>alert" not in doc
    assert "&lt;script&gt;" in doc


def test_printable_document_shouts_when_the_chain_is_broken(client, vendor, monkeypatch):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    from app.services import audit as audit_svc

    async def broken(_db):
        return {"ok": False, "entries": 5, "broken_at": 3, "reason": "hash mismatch"}

    monkeypatch.setattr(audit_svc, "verify", broken)
    doc = client.get("/api/evidence/pack.html").text
    assert "BROKEN" in doc and "class='broken'" in doc
    assert "do not rely on this report" in doc


def test_preview_is_free_and_shows_the_gap(client):
    r = client.get("/api/evidence/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["licensed"] is False
    assert "coverage" in body and "audit" in body
    assert "matched" not in body, "the free preview must not include per-CVE detail"


def test_activate_then_export(client, vendor, monkeypatch):
    monkeypatch.setitem(cpe.CPE_MAP, "7zip.7zip", cpe.CpeEntry("7-zip", "7-zip"))
    from app.services import software_updates as sw

    async def fake_list():
        return [sw.InstalledSoftwareInfo("7zip.7zip", "7-Zip", "26.02")], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    client.post("/api/updates/inventory/refresh", headers=CSRF)

    r = client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    assert r.status_code == 200 and r.json()["can_export_evidence"] is True

    pack = client.get("/api/evidence/pack").json()
    assert pack["stamp_kind"] == "sha256-content-hash"
    assert len(pack["content_sha256"]) == 64
    assert pack["pack"]["licensee"] == "Test Clinic"
    assert pack["pack"]["coverage"]["mapped"] == 1


def test_activating_a_forged_key_is_rejected_by_the_api(client, vendor):
    other = Ed25519PrivateKey.generate()
    payload = json.dumps({"tier": "partner"}, sort_keys=True).encode()
    forged = f"HU1.{_b64(payload)}.{_b64(other.sign(payload))}"
    r = client.post("/api/evidence/license/activate", json={"key": forged}, headers=CSRF)
    assert r.status_code == 400
    assert client.get("/api/evidence/pack").status_code == 402


def test_clearing_the_license_revokes_export(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    assert client.get("/api/evidence/pack").status_code == 200
    client.post("/api/evidence/license/clear", headers=CSRF)
    assert client.get("/api/evidence/pack").status_code == 402


# --- the pack's content and its claims -------------------------------------
def test_stamp_is_reproducible_and_excludes_itself(client, vendor):
    """A reader must be able to recompute the stamp from the pack they hold."""
    import hashlib

    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    built = client.get("/api/evidence/pack").json()
    recomputed = hashlib.sha256(evidence._canonical(built["pack"]).encode("utf-8")).hexdigest()
    assert recomputed == built["content_sha256"]


def test_pack_never_claims_to_be_signed():
    """Wording IS the product: a SHA-256 is not a signature, and implying otherwise
    is the overclaim that loses the auditor. The word may appear only in a DENIAL."""
    joined_en = " ".join(v for k, v in evidence.COPY.items() if k.endswith("_en")).lower()
    joined_ar = " ".join(v for k, v in evidence.COPY.items() if k.endswith("_ar"))

    # No positive claim of signing anywhere.
    for claim in ("digitally signed", "signed report", "signed by", "is a digital signature"):
        assert claim not in joined_en, claim
    assert "توقيع رقميّ" not in joined_ar or "ليست توقيعًا" in joined_ar

    # And the denial is explicit, in both languages.
    assert "not a digital signature" in evidence.COPY["stamp_en"].lower()
    assert "ليست توقيعًا" in evidence.COPY["stamp_ar"]
    assert "hash-stamped" in joined_en
    assert "مبصوم" in joined_ar


def test_pack_states_its_limits_and_never_claims_clean():
    ar = evidence.COPY["limits_ar"] + evidence.COPY["coverage_ar"]
    en = (evidence.COPY["limits_en"] + evidence.COPY["coverage_en"]).lower()
    assert "ليس شهادة اعتماد" in ar
    assert "not a certification" in en
    assert "must not be read as proof" in en
    assert "التغطية جزئيّة" in ar


def test_integrity_copy_says_detect_not_prevent():
    """The exact claim a rejected draft got wrong — pinned so it cannot come back."""
    assert "لا يمنعه" in evidence.COPY["integrity_ar"]
    assert "does not prevent it" in evidence.COPY["integrity_en"]
    assert "immutable" not in evidence.COPY["integrity_en"].lower()


def test_pack_includes_chain_verification_and_head(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    body = client.get("/api/evidence/pack").json()["pack"]
    assert body["audit"]["chain_ok"] is True
    assert len(body["audit"]["head_hash"]) == 64
    assert body["audit"]["entries"] >= 1, "the activation itself is an audited event"


def test_csv_marks_no_covering_range_rather_than_clean(client, vendor, monkeypatch):
    monkeypatch.setitem(cpe.CPE_MAP, "7zip.7zip", cpe.CpeEntry("7-zip", "7-zip"))
    from app.services import software_updates as sw

    async def fake_list():
        return [
            sw.InstalledSoftwareInfo("7zip.7zip", "7-Zip", "26.02"),
            sw.InstalledSoftwareInfo("Nope.App", "Nope", "1.0"),
        ], False

    monkeypatch.setattr("app.routers.updates.list_installed_software", fake_list)
    client.post("/api/updates/inventory/refresh", headers=CSRF)
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)

    text = client.get("/api/evidence/pack.csv").text
    assert "product_id,name,installed_version" in text
    assert "no_cpe_mapping" in text
    assert "clean" not in text.lower()


def test_export_is_audited(client, vendor):
    client.post("/api/evidence/license/activate", json={"key": vendor()}, headers=CSRF)
    client.get("/api/evidence/pack")
    kinds = [e["kind"] for e in client.get("/api/audit/events").json()["events"]]
    assert "evidence_export" in kinds
    assert "license_activate" in kinds
    assert client.get("/api/audit/verify").json()["ok"] is True
