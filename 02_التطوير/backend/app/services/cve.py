"""
Vulnerability lookup via the NVD (National Vulnerability Database) API 2.0.

Network discovery only gives a device's VENDOR (from its MAC OUI), not the exact
product/version, so we surface "known vulnerabilities associated with this
vendor" by keyword. Results are cached in the DB (CVECacheORM) because NVD
rate-limits anonymous callers to ~5 requests / 30 seconds. This is an online
enhancement: with no internet, cached results are still served.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import CVECacheORM

NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
# NVD anonymous limit is ~5 requests / 30s; the floor stays comfortably under it.
_THROTTLE_SECONDS = 6.5
_THROTTLE_CEILING = 120.0


class CVEError(RuntimeError):
    """Raised when NVD cannot be reached and there is no cached result."""


class CVERateLimited(CVEError):
    """NVD returned 429/403 (rate limited). Carries Retry-After if present."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("NVD rate limit reached")
        self.retry_after = retry_after


class _NvdThrottle:
    """AIMD pacing for anonymous NVD calls.

    The floor is the safe anonymous rate (~6.5s); we never go below it because
    anonymous callers have no headroom to speed up. On a 429/403 we back off
    multiplicatively (honoring Retry-After), then narrow additively back toward
    the floor after sustained success — so transient pushback widens the gap
    instead of hammering the limit, and it recovers on its own.
    """

    def __init__(
        self, floor: float = _THROTTLE_SECONDS, ceiling: float = _THROTTLE_CEILING
    ) -> None:
        self.floor = floor
        self.ceiling = ceiling
        self.delay = floor

    def current(self) -> float:
        return self.delay

    def on_success(self) -> None:
        self.delay = max(self.floor, self.delay - 1.0)  # additive decrease toward the floor

    def on_rate_limited(self, retry_after: float | None = None) -> None:
        backed = min(self.ceiling, self.delay * 2)  # multiplicative increase
        if retry_after and retry_after > 0:
            backed = max(backed, min(self.ceiling, float(retry_after)))
        self.delay = backed


_throttle = _NvdThrottle()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """NVD sends Retry-After in seconds when it throttles; parse it defensively."""
    val = resp.headers.get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite may return naive datetimes; treat them as UTC for comparisons."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _extract_cvss(cve: dict) -> tuple[float, str]:
    metrics = cve.get("metrics", {})
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        arr = metrics.get(key) or []
        if arr:
            cvss = arr[0].get("cvssData", {})
            score = float(cvss.get("baseScore", 0.0) or 0.0)
            sev = (cvss.get("baseSeverity") or arr[0].get("baseSeverity") or "").upper()
            return score, sev
    return 0.0, ""


def parse_cves(data: dict, limit: int) -> list[dict]:
    """Extract the top `limit` CVEs (most severe, then most recent)."""
    out: list[dict] = []
    for item in data.get("vulnerabilities", []):
        cve = item.get("cve", {})
        cid = cve.get("id", "")
        if not cid:
            continue
        score, sev = _extract_cvss(cve)
        desc = next(
            (d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"),
            "",
        )
        out.append(
            {
                "id": cid,
                "score": score,
                "severity": sev,
                "published": (cve.get("published") or "")[:10],
                "description": desc[:300],
                "url": f"https://nvd.nist.gov/vuln/detail/{cid}",
            }
        )
    out.sort(
        key=lambda c: (_SEVERITY_RANK.get(c["severity"], 0), c["score"], c["published"]),
        reverse=True,
    )
    return out[:limit]


async def _fetch_nvd(keyword: str, results_per_page: int = 100) -> dict:
    params = {"keywordSearch": keyword, "resultsPerPage": results_per_page}
    # Split connect vs read: NVD's server processing can be slow, so give the read
    # leg room while keeping the connect leg tight instead of one blunt 25s bound.
    timeout = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(NVD_URL, params=params, headers={"User-Agent": "HomeUpdater/0.1"})
    if resp.status_code in (429, 403):  # rate limited — surface it so the throttle backs off
        raise CVERateLimited(_retry_after_seconds(resp))
    resp.raise_for_status()
    return resp.json()


async def lookup_cves(
    keyword: str,
    db: AsyncSession,
    limit: int = 8,
    ttl_hours: int = 24,
    force: bool = False,
) -> dict:
    """Vendor CVE summary, served from the 24h DB cache or fetched from NVD."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": "", "total_results": 0, "cves": [], "fetched_at": None, "cached": False}

    row = (
        await db.execute(select(CVECacheORM).where(CVECacheORM.keyword == keyword))
    ).scalar_one_or_none()

    is_fresh = (
        row is not None
        and not force
        and _aware(row.fetched_at) is not None
        and (datetime.now(UTC) - _aware(row.fetched_at)) < timedelta(hours=ttl_hours)
    )
    if is_fresh:
        return {**row.to_dict(), "cached": True}

    try:
        data = await _fetch_nvd(keyword)
    except CVERateLimited as exc:
        _throttle.on_rate_limited(exc.retry_after)
        logger.warning(
            f"NVD rate-limited for {keyword!r}; backing off to {_throttle.current():.0f}s"
        )
        if row is not None:  # serve stale cache while we back off
            return {**row.to_dict(), "cached": True, "stale": True}
        raise
    except Exception as exc:
        logger.warning(f"NVD lookup for {keyword!r} failed: {exc}")
        if row is not None:  # serve stale cache on network error
            return {**row.to_dict(), "cached": True, "stale": True}
        raise CVEError(f"NVD unreachable: {exc}") from exc

    cves = parse_cves(data, limit)
    total = int(data.get("totalResults", 0) or 0)
    now = datetime.now(UTC)
    if row is None:
        row = CVECacheORM(keyword=keyword)
        db.add(row)
    row.total_results = total
    row.data = json.dumps(cves, ensure_ascii=False)
    row.fetched_at = now
    await db.commit()
    _throttle.on_success()  # a clean fetch narrows the gap back toward the floor

    return {
        "keyword": keyword,
        "total_results": total,
        "cves": cves,
        "fetched_at": now.isoformat(),
        "cached": False,
    }


async def get_cached(keyword: str, db: AsyncSession) -> dict | None:
    """Return the cached summary for a keyword, or None (no NVD call)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    row = (
        await db.execute(select(CVECacheORM).where(CVECacheORM.keyword == keyword))
    ).scalar_one_or_none()
    return row.to_dict() if row else None


async def refresh_vendors(vendors: list[str], db: AsyncSession, ttl_hours: int = 24) -> dict:
    """Fetch CVEs for each vendor, throttled to respect NVD's rate limit.

    Only stale/missing vendors hit the network; cached ones are skipped (no
    sleep), so repeated refreshes are fast.
    """
    refreshed, errors = 0, 0
    for vendor in vendors:
        before = await get_cached(vendor, db)
        was_fresh = (
            before is not None
            and _aware(datetime.fromisoformat(before["fetched_at"])) is not None
            and (datetime.now(UTC) - _aware(datetime.fromisoformat(before["fetched_at"])))
            < timedelta(hours=ttl_hours)
        )
        if was_fresh:
            continue
        try:
            result = await lookup_cves(vendor, db, ttl_hours=ttl_hours)
            if not result.get("cached"):
                refreshed += 1
        except CVEError:
            errors += 1
        # Every non-fresh vendor above issued a real NVD request (fresh ones were
        # skipped). Pace EVERY one by the current AIMD delay — INCLUDING the
        # rate-limited case, where lookup_cves already widened _throttle and then
        # returned stale / raised. Gating this sleep on a fresh result (the old
        # behaviour) let a 429/403 storm run back-to-back and defeated the backoff.
        await asyncio.sleep(_throttle.current())
    return {"refreshed": refreshed, "errors": errors, "total_vendors": len(vendors)}
