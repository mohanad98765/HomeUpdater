"""The Evidence Pack — the artifact a customer actually pays for.

What it is: a point-in-time record that states, for one machine, what software is
installed, which vulnerabilities apply to those exact versions, what was patched,
and whether the audit trail behind those claims is intact — plus a content hash so
the document can be shown to be the same one that was issued.

Deliberate wording, because this is sold as evidence and the wording IS the product:
  * "hash-stamped" (مبصومة بالهاش), never "signed". There is no signing key here, and
    calling a SHA-256 a signature would be exactly the overclaim that destroys trust
    with the auditor it is meant to convince. A real signature can be added later
    without changing the pack's shape.
  * Coverage is reported as a number, and the un-matched products are listed WITH
    reasons. A pack that silently covers a third of an estate is worse than one that
    says it covers a third.
  * "No findings" is written as "no NVD range covers this version", not "clean".
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..models.orm import HUB_DEVICE_ID, InstalledSoftwareORM, WindowsUpdateORM
from . import audit, cpe, cve

# --- the static Arabic/English copy ----------------------------------------
# Written deliberately: every sentence is either verifiable from the data in the
# pack or an explicit limitation. No regulatory control IDs and no authority names
# are cited — the standard's numbering must be verified against an issued (not
# draft) document before any of it is printed on a customer-facing report.
COPY = {
    "cover_title_ar": "حزمة الدليل — تقرير التحديثات والثغرات",
    "cover_title_en": "Evidence Pack — Patch & Vulnerability Report",
    "cover_sub_ar": "سجلّ لحظيّ لحالة جهاز واحد، صادر عن HomeUpdater ومبصوم بالهاش",
    "cover_sub_en": (
        "A point-in-time record for one machine, issued by HomeUpdater and hash-stamped"
    ),
    "scope_ar": (
        "يشمل هذا التقرير جهازًا واحدًا هو الجهاز الذي يعمل عليه التطبيق، وبياناته "
        "مأخوذة من جرد البرامج المثبَّتة عليه وسجلّ التحديثات المُثبَّتة، في التاريخ "
        "والوقت المذكورَين أعلاه. لا يشمل أجهزةً أخرى على الشبكة إلا إن ذُكرت صراحةً."
    ),
    "scope_en": (
        "This report covers one machine — the one running the application — using its "
        "installed-software inventory and its record of applied updates, as of the "
        "timestamp above. Other devices on the network are not included unless listed."
    ),
    "method_ar": (
        "تُجرد البرامج المثبَّتة مع إصداراتها، ثم يُسأل مصدر الثغرات الرسميّ (NVD) عن "
        "الثغرات المنطبقة على كل منتج بإصداره المثبَّت تحديدًا، باستخدام اسم CPE 2.3 "
        "كامل. تُدرَج مع كل ثغرة نطاق الإصدارات الذي جعلها منطبقة، ليتمكّن القارئ من "
        "مراجعة الاستنتاج بنفسه لا تصديقه فقط."
    ),
    "method_en": (
        "Installed products and their versions are inventoried, then the official "
        "vulnerability source (NVD) is queried per product using a full CPE 2.3 name "
        "so the installed version itself is evaluated. Each finding is accompanied by "
        "the version range that made it apply, so a reader can audit the conclusion "
        "rather than take it on faith."
    ),
    "coverage_ar": (
        "التغطية جزئيّة وتُذكَر نسبتها في هذا التقرير. بعض المنتجات لا يوجد لها تعريف "
        "CPE موثوق، أو تُبلّغ عن إصدار لا يقبل المقارنة، فتُدرَج في قائمة «غير مُطابَق» "
        "مع سبب استثنائها. وجود منتج في تلك القائمة يعني انعدام التغطية لا انعدام الخطر."
    ),
    "coverage_en": (
        "Coverage is partial and its percentage is stated in this report. Some products "
        "have no verified CPE, or report a version that cannot be compared, and are "
        "listed as not-matched with the reason. Being on that list means no coverage, "
        "not no risk."
    ),
    "limits_ar": (
        "هذا التقرير ليس شهادة اعتماد، ولا بديلًا عن ماسح ثغرات مُعتمَد أو اختبار "
        "اختراق. و«لا نتائج» لمنتجٍ ما تعني أن المصدر الرسميّ لا يُدرج نطاق إصدارات "
        "يشمل الإصدار المثبَّت، ولا تُقرأ إثباتًا لخلوّه من الثغرات."
    ),
    "limits_en": (
        "This report is not a certification, and not a substitute for an accredited "
        "vulnerability scanner or a penetration test. For a given product, no findings "
        "means the official source lists no version range covering the installed "
        "version — it must not be read as proof that the product is free of flaws."
    ),
    "integrity_ar": (
        "الأحداث التي يستند إليها التقرير مُسجَّلة في سجلّ يُضاف إليه فقط، كل سطر فيه "
        "مربوط بتجزئة السطر السابق. لذلك يُكشَف أي تعديل أو حذف لاحق لسطرٍ واحد عند "
        "التحقّق من السلسلة، ونتيجة هذا التحقّق مُدرجة أدناه. ملاحظة صريحة: هذا "
        "يَكشِف التلاعب ولا يمنعه؛ ومن يملك الكتابة على قاعدة البيانات يستطيع إعادة "
        "بناء السلسلة كاملةً. ولهذا تُدرَج بصمة السلسلة (digest) هنا: الاحتفاظ بها "
        "خارج الجهاز يجعل استبدال القاعدة بالكامل مكشوفًا."
    ),
    "integrity_en": (
        "The events behind this report are kept in an append-only log where each entry "
        "is chained to the hash of the previous one, so editing or deleting a single "
        "entry is detected when the chain is verified; that verification result is "
        "included below. Stated plainly: this detects tampering, it does not prevent "
        "it — anyone able to write the database could rebuild the whole chain. That is "
        "why the chain digest is printed here: keeping a copy off the machine makes a "
        "wholesale replacement detectable."
    ),
    "stamp_ar": (
        "بصمة المحتوى أدناه محسوبة على محتوى هذا التقرير نفسه (SHA-256). هي ليست "
        "توقيعًا رقميًّا: تُثبِت أن النسخة التي بين يديك مطابقة للنسخة الصادرة، ولا "
        "تُثبِت هويّة جهة الإصدار."
    ),
    "stamp_en": (
        "The content stamp below is a SHA-256 over this report's own content. It is "
        "not a digital signature: it shows the copy you hold matches the one issued, "
        "but does not attest to the issuer's identity."
    ),
}


def _canonical(payload: dict) -> str:
    return audit.canonical(payload)


async def build(db: AsyncSession, *, licensee: str = "") -> dict:
    """Assemble the pack. Read-only: it reports state, it never changes it."""
    now = datetime.now(UTC)

    inventory = (
        (
            await db.execute(
                select(InstalledSoftwareORM)
                .where(InstalledSoftwareORM.device_id == HUB_DEVICE_ID)
                .order_by(InstalledSoftwareORM.name)
            )
        )
        .scalars()
        .all()
    )

    matched: list[dict] = []
    unmatched: list[dict] = []
    for row in inventory:
        identity = cpe.resolve(row.product_id, row.version)
        if identity is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    "version": row.version,
                    "reason": (
                        "no_cpe_mapping"
                        if row.product_id not in cpe.CPE_MAP
                        else "version_not_comparable"
                    ),
                    "detail": cpe.UNMAPPABLE.get(row.product_id, ""),
                }
            )
            continue
        cached = await cve.get_cached(identity.cpe_name, db)  # never calls NVD here
        if cached is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    "version": row.version,
                    "reason": "not_yet_checked",
                    "detail": "",
                }
            )
            continue
        cves = cached.get("cves", [])
        bounded = [
            c for c in cves if (c.get("applies_because") or {}).get("precision") != "unbounded"
        ]
        broad = [
            c for c in cves if (c.get("applies_because") or {}).get("precision") == "unbounded"
        ]
        matched.append(
            {
                "product_id": row.product_id,
                "name": row.name,
                "version": identity.version,
                "cpe_name": identity.cpe_name,
                "findings": bounded,
                "broad_matches": [c["id"] for c in broad],
                "checked_at": cached.get("fetched_at"),
            }
        )

    applied = (
        (
            await db.execute(
                select(WindowsUpdateORM).where(
                    WindowsUpdateORM.device_id == HUB_DEVICE_ID,
                    WindowsUpdateORM.is_installed.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    chain = await audit.verify(db)
    head = await audit.digest(db)

    body = {
        "generated_at": now.isoformat(),
        "app_version": __version__,
        "licensee": licensee,
        "scope": {"machines": 1, "note": "the machine running HomeUpdater"},
        "inventory_total": len(inventory),
        "coverage": cpe.coverage([r.product_id for r in inventory]),
        "matched": matched,
        "unmatched": unmatched,
        "findings_total": sum(len(m["findings"]) for m in matched),
        "broad_matches_total": sum(len(m["broad_matches"]) for m in matched),
        "updates_applied": [
            {"update_id": u.update_id, "title": u.title, "kind": u.kind, "result": u.install_result}
            for u in applied
        ][:200],
        "audit": {
            "chain_ok": chain["ok"],
            "entries": chain["entries"],
            "broken_at": chain["broken_at"],
            "reason": chain["reason"],
            "head_seq": head["head_seq"],
            "head_hash": head["head_hash"],
        },
        "copy": COPY,
    }
    # The stamp covers the canonical body, so it can be recomputed by anyone holding
    # the pack. It is placed OUTSIDE the hashed body for that reason.
    stamp = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    return {"pack": body, "content_sha256": stamp, "stamp_kind": "sha256-content-hash"}


def to_csv(pack: dict) -> str:
    """The findings table as CSV — what a reviewer actually pastes into a workbook."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(
        [
            "product_id",
            "name",
            "installed_version",
            "cpe",
            "cve",
            "severity",
            "score",
            "applies_because",
            "status",
        ]
    )
    body = pack["pack"]
    for m in body["matched"]:
        if not m["findings"]:
            w.writerow(
                [
                    m["product_id"],
                    m["name"],
                    m["version"],
                    m["cpe_name"],
                    "",
                    "",
                    "",
                    "",
                    "no_covering_range",
                ]
            )
        for c in m["findings"]:
            r = c.get("applies_because") or {}
            bounds = " ".join(
                f"{k}={v}" for k, v in r.items() if k.startswith(("start_", "end_")) and v
            )
            w.writerow(
                [
                    m["product_id"],
                    m["name"],
                    m["version"],
                    m["cpe_name"],
                    c["id"],
                    c.get("severity", ""),
                    c.get("score", ""),
                    bounds,
                    "applies",
                ]
            )
    for u in body["unmatched"]:
        w.writerow(
            [u["product_id"], "", u["version"], "", "", "", "", u.get("detail", ""), u["reason"]]
        )
    return out.getvalue()
