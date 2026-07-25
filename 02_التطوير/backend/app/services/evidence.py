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
import html
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
        identity = cpe.resolve(row.product_id, row.version, row.name)
        if identity is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    # The NAME matters in the pack too: an auditor reads "Microsoft 365",
                    # not "ARP\Machine\X64\O365HomePremRetail - ar-sa".
                    "name": row.name,
                    "version": row.version,
                    "reason": cpe.unmatched_reason(row.product_id, row.version, row.name),
                    "detail": cpe.exclusion_detail(row.product_id, row.name),
                }
            )
            continue
        cached = await cve.get_cached(identity.cpe_name, db)  # never calls NVD here
        if cached is None:
            unmatched.append(
                {
                    "product_id": row.product_id,
                    "name": row.name,
                    "version": row.version,
                    "reason": "not_yet_checked",
                    "detail": "",
                }
            )
            continue
        # Exactly the same classifier the security page uses — the pack must never
        # count a finding the screen refuses to count, or vice versa.
        bounded, broad = cve.counted_and_uncounted(cached.get("cves", []), identity.version)
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
        "coverage": cpe.coverage([(r.product_id, r.name) for r in inventory]),
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


_PRINT_CSS = """
  :root { --ink:#111; --muted:#555; --line:#d4d4d4; --bad:#b00020; --warn:#8a5a00; }
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Tahoma, sans-serif; color: var(--ink);
         margin: 0 auto; max-width: 900px; padding: 24px; line-height: 1.6; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 22px 0 8px; border-bottom: 2px solid var(--line);
       padding-bottom: 4px; }
  .sub { color: var(--muted); margin: 0 0 16px; }
  .meta { border: 1px solid var(--line); padding: 10px 14px; margin-bottom: 8px; }
  .meta div { display: flex; gap: 8px; }
  .meta b { min-width: 190px; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; margin-bottom: 8px; }
  th, td { border: 1px solid var(--line); padding: 5px 7px; text-align: start;
           vertical-align: top; word-break: break-word; }
  th { background: #f2f2f2; }
  code { font-family: Consolas, monospace; font-size: 11px; }
  .note { font-size: 12px; color: var(--muted); }
  .limits { border: 1px solid var(--warn); padding: 10px 14px; font-size: 12px; }
  .broken { color: var(--bad); font-weight: 700; }
  .stamp { font-family: Consolas, monospace; font-size: 12px; word-break: break-all; }
  .toolbar { margin-bottom: 16px; }
  button { font: inherit; padding: 6px 14px; cursor: pointer; }
  @media print { .toolbar { display: none; } body { max-width: none; padding: 0; }
    table { page-break-inside: auto; } tr { page-break-inside: avoid; }
    thead { display: table-header-group; } h2 { page-break-after: avoid; } }
"""


def _esc(value) -> str:
    """Escape everything that reaches the document: product names come from the
    machine's registry and are attacker-influenced in the general case, and this file
    is opened in a browser by the person we are trying to convince."""
    return html.escape("" if value is None else str(value), quote=True)


def _range_text(applies: dict | None) -> str:
    if not applies:
        return ""
    parts = []
    for key, label in (
        ("start_including", "from (incl.)"),
        ("start_excluding", "after"),
        ("end_including", "up to (incl.)"),
        ("end_excluding", "before"),
    ):
        if applies.get(key):
            parts.append(f"{label} {applies[key]}")
    return " · ".join(parts)


def to_html(pack: dict) -> str:
    """A print-ready document of the pack — Arabic + English, one self-contained file.

    Deliberately HTML and not a generated PDF: there is no PDF engine in the build and
    no embedded Arabic font, and a PDF with broken Arabic shaping would be worse than
    none. A browser (the app's own WebView2 included) shapes Arabic correctly and
    prints to PDF in one step, so the honest deliverable is a document that prints.
    """
    body = pack["pack"]
    stamp = pack.get("content_sha256", "")
    c = body.get("copy", COPY)
    cov = body.get("coverage", {})
    audit_info = body.get("audit", {})
    by_reason = cov.get("by_reason", {})

    rows_findings = []
    for m in body.get("matched", []):
        for f in m.get("findings", []):
            rows_findings.append(
                "<tr>"
                f"<td>{_esc(m.get('name'))}</td>"
                f"<td>{_esc(m.get('version'))}</td>"
                f"<td><code>{_esc(m.get('cpe_name'))}</code></td>"
                f"<td>{_esc(f.get('id'))}</td>"
                f"<td>{_esc(f.get('severity'))}</td>"
                f"<td>{_esc(f.get('score'))}</td>"
                f"<td>{_esc(_range_text(f.get('applies_because')))}</td>"
                "</tr>"
            )
    rows_notcounted = []
    for m in body.get("matched", []):
        for f in m.get("broad_matches", []):
            fid = f if isinstance(f, str) else f.get("id")
            why = "" if isinstance(f, str) else f.get("precision", "")
            rows_notcounted.append(
                f"<tr><td>{_esc(m.get('name'))}</td><td>{_esc(fid)}</td><td>{_esc(why)}</td></tr>"
            )
    rows_unmatched = []
    for u in body.get("unmatched", []):
        rows_unmatched.append(
            "<tr>"
            f"<td>{_esc(u.get('name') or u.get('product_id'))}</td>"
            f"<td>{_esc(u.get('version'))}</td>"
            f"<td>{_esc(u.get('reason'))}</td>"
            f"<td>{_esc(u.get('detail'))}</td>"
            "</tr>"
        )
    rows_updates = []
    for u in body.get("updates_applied", []):
        rows_updates.append(
            "<tr>"
            f"<td>{_esc(u.get('title'))}</td>"
            f"<td>{_esc(u.get('kind'))}</td>"
            f"<td>{_esc(u.get('result'))}</td>"
            f"<td><code>{_esc(u.get('update_id'))}</code></td>"
            "</tr>"
        )

    chain_ok = bool(audit_info.get("chain_ok"))
    chain_line = (
        f"سليمة / intact — {_esc(audit_info.get('entries'))} حدثًا"
        if chain_ok
        else (
            "<span class='broken'>مكسورة عند السجلّ "
            f"{_esc(audit_info.get('broken_at'))} / BROKEN — do not rely on this report"
            " until the cause is known</span>"
        )
    )

    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>{_esc(c['cover_title_ar'])}</title><style>{_PRINT_CSS}</style></head><body>
<div class="toolbar"><button onclick="window.print()">طباعة / حفظ PDF
— Print / Save as PDF</button></div>
<h1>{_esc(c['cover_title_ar'])}</h1>
<p class="sub">{_esc(c['cover_title_en'])}<br>{_esc(c['cover_sub_ar'])}</p>
<div class="meta">
  <div><b>المرخَّص له / Licensee</b><span>{_esc(body.get('licensee') or '—')}</span></div>
  <div><b>وقت الإصدار / Generated</b><span>{_esc(body.get('generated_at'))}</span></div>
  <div><b>إصدار التطبيق / App version</b><span>{_esc(body.get('app_version'))}</span></div>
  <div><b>النطاق / Scope</b><span>{_esc(body.get('scope', {}).get('note'))}</span></div>
  <div><b>منتجات مجرودة / Products</b><span>{_esc(body.get('inventory_total'))}</span></div>
</div>

<h2>النطاق والمنهج — Scope &amp; method</h2>
<p class="note">{_esc(c['scope_ar'])}</p>
<p class="note">{_esc(c['method_ar'])}</p>

<h2>التغطية — Coverage</h2>
<p class="note">{_esc(c['coverage_ar'])}</p>
<div class="meta">
  <div><b>مُطابَق دقيقًا / Precisely matched</b><span>{_esc(cov.get('mapped'))} من
      {_esc(cov.get('total'))} ({_esc(cov.get('percent'))}%)</span></div>
  <div><b>من القابل للمطابقة / Of addressable</b>
      <span>{_esc(cov.get('addressable_percent'))}%
      ({_esc(cov.get('addressable_total'))})</span></div>
  <div><b>حِزم متجر / Store packages</b><span>{_esc(by_reason.get('store_package'))}</span></div>
  <div><b>استثناءات موثَّقة / Documented</b>
      <span>{_esc(by_reason.get('documented_exclusion'))}</span></div>
  <div><b>لم تُدرَس / Not investigated</b>
      <span>{_esc(by_reason.get('not_investigated'))}</span></div>
</div>

<h2>الثغرات المنطبقة على الإصدارات المثبَّتة — Findings ({_esc(body.get('findings_total'))})</h2>
<table><thead><tr><th>المنتج</th><th>الإصدار</th><th>CPE</th><th>الثغرة</th>
<th>الخطورة</th><th>الدرجة</th><th>تنطبق لأنها</th></tr></thead>
<tbody>{''.join(rows_findings) or '<tr><td colspan="7">—</td></tr>'}</tbody></table>

<h2>سجلّات فُحصت ولم تُحتسَب — Checked, not counted ({_esc(body.get('broad_matches_total'))})</h2>
<table><thead><tr><th>المنتج</th><th>الثغرة</th><th>سبب عدم الاحتساب</th></tr></thead>
<tbody>{''.join(rows_notcounted) or '<tr><td colspan="3">—</td></tr>'}</tbody></table>

<h2>غير مطابَق مع السبب — Not matched, with the reason ({len(body.get('unmatched', []))})</h2>
<table><thead><tr><th>المنتج</th><th>الإصدار</th><th>السبب</th><th>التفصيل</th></tr></thead>
<tbody>{''.join(rows_unmatched) or '<tr><td colspan="4">—</td></tr>'}</tbody></table>

<h2>التحديثات المُطبَّقة — Applied updates ({len(body.get('updates_applied', []))})</h2>
<table><thead><tr><th>العنوان</th><th>النوع</th><th>النتيجة</th><th>المعرّف</th></tr></thead>
<tbody>{''.join(rows_updates) or '<tr><td colspan="4">—</td></tr>'}</tbody></table>

<h2>سلامة السجلّ — Audit trail</h2>
<p class="note">{_esc(c['integrity_ar'])}</p>
<div class="meta">
  <div><b>حالة السلسلة / Chain</b><span>{chain_line}</span></div>
  <div><b>بصمة السلسلة / Digest</b>
      <span class="stamp">{_esc(audit_info.get('head_hash'))}</span></div>
</div>

<h2>بصمة المحتوى — Content stamp</h2>
<p class="note">{_esc(c['stamp_ar'])}</p>
<p class="stamp">SHA-256: {_esc(stamp)}</p>

<h2>حدود التقرير — Limits</h2>
<div class="limits"><p>{_esc(c['limits_ar'])}</p><p>{_esc(c['limits_en'])}</p></div>
</body></html>
"""


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
