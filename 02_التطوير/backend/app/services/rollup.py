"""Multi-site roll-up — a partner's view over many sites, without a cloud console.

Design choice, deliberately conservative: a partner aggregates by IMPORTING the
evidence-pack files each site produced, not by having every site phone home. That
keeps the product's core promise intact (nothing leaves the customer's network),
needs no multi-tenant backend, and is what a 15-office reseller actually asks for —
one place to see who is non-compliant.

The security-meaningful part is verification: each imported pack is re-hashed and
compared against its own stamp, so a pack that was edited after issue is FLAGGED
rather than quietly folded into the totals. An aggregate that averages tampered
inputs is worse than no aggregate, because it launders them.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime

from . import audit


def verify_pack(entry: dict) -> tuple[bool, str]:
    """Re-compute an imported pack's stamp. Returns ``(ok, reason)``.

    A pack is trustworthy only if the hash over its own canonical body matches the
    stamp it carries — the same computation the issuing machine did, so a partner can
    check it without contacting anyone.
    """
    if not isinstance(entry, dict):
        return False, "not_an_object"
    body = entry.get("pack")
    stamp = entry.get("content_sha256", "")
    if not isinstance(body, dict) or not stamp:
        return False, "missing_pack_or_stamp"
    recomputed = hashlib.sha256(audit.canonical(body).encode("utf-8")).hexdigest()
    if recomputed != stamp:
        return False, "stamp_mismatch"
    return True, ""


def _site_name(body: dict, fallback: str) -> str:
    return (body.get("licensee") or "").strip() or fallback


def build(packs: list[dict]) -> dict:
    """Aggregate verified packs; list rejected ones separately with a reason."""
    sites: list[dict] = []
    rejected: list[dict] = []
    seen_stamps: set[str] = set()

    for i, entry in enumerate(packs or []):
        ok, reason = verify_pack(entry)
        if not ok:
            rejected.append({"index": i, "reason": reason, "site": ""})
            continue
        # The same file imported twice — trivially easy when a partner drags a folder
        # in — would otherwise double every total. Identical stamp = identical pack, so
        # count it once and SAY that a copy was set aside instead of inflating silently.
        if entry["content_sha256"] in seen_stamps:
            rejected.append({"index": i, "reason": "duplicate", "site": ""})
            continue
        seen_stamps.add(entry["content_sha256"])
        body = entry["pack"]
        cov = body.get("coverage") or {}
        audit_info = body.get("audit") or {}
        sites.append(
            {
                "site": _site_name(body, f"site-{i + 1}"),
                "generated_at": body.get("generated_at", ""),
                "app_version": body.get("app_version", ""),
                "inventory_total": int(body.get("inventory_total", 0) or 0),
                "coverage_percent": float(cov.get("percent", 0.0) or 0.0),
                "coverage_mapped": int(cov.get("mapped", 0) or 0),
                "findings_total": int(body.get("findings_total", 0) or 0),
                "broad_matches_total": int(body.get("broad_matches_total", 0) or 0),
                "unmatched_total": len(body.get("unmatched") or []),
                "chain_ok": bool(audit_info.get("chain_ok", False)),
                "chain_head": audit_info.get("head_hash", ""),
                "stamp": entry["content_sha256"],
            }
        )

    # Sites needing attention first: a broken chain outranks a high finding count,
    # because it invalidates the report rather than merely reporting bad news.
    sites.sort(key=lambda s: (s["chain_ok"], -s["findings_total"], s["coverage_percent"]))

    verified = len(sites)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "sites": sites,
        "rejected": rejected,
        "totals": {
            "sites_verified": verified,
            "sites_rejected": len(rejected),
            # PRODUCTS, not machines: a pack covers one machine and counts the software
            # installed on it. Calling this "devices" read as "230 devices" for two PCs.
            "products": sum(s["inventory_total"] for s in sites),
            "findings": sum(s["findings_total"] for s in sites),
            "sites_with_findings": sum(1 for s in sites if s["findings_total"] > 0),
            "sites_with_broken_chain": sum(1 for s in sites if not s["chain_ok"]),
            # Averaged over VERIFIED sites only — rejected packs are never blended in.
            "avg_coverage_percent": (
                round(sum(s["coverage_percent"] for s in sites) / verified, 1) if verified else 0.0
            ),
        },
    }


def to_csv(rollup: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(
        [
            "site",
            "generated_at",
            "products",
            "coverage_percent",
            "findings",
            "broad_matches",
            "unmatched",
            "chain_ok",
            "stamp",
        ]
    )
    for s in rollup["sites"]:
        w.writerow(
            [
                s["site"],
                s["generated_at"],
                s["inventory_total"],
                s["coverage_percent"],
                s["findings_total"],
                s["broad_matches_total"],
                s["unmatched_total"],
                "yes" if s["chain_ok"] else "NO",
                s["stamp"][:16],
            ]
        )
    # Rejected packs are printed in the same file on purpose: a partner must see
    # that something was excluded, not discover a silently shorter list.
    for r in rollup["rejected"]:
        w.writerow([f"(rejected #{r['index']})", "", "", "", "", "", "", "REJECTED", r["reason"]])
    return out.getvalue()
