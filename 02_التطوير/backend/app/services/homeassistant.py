"""
Home Assistant integration via its REST API.

Home Assistant already tracks firmware/software updates for many smart-home
devices as ``update.*`` entities. We fetch those so they can be shown — and
installed — from HomeUpdater's single dashboard. Auth is a Long-Lived Access
Token (Settings -> Profile -> Long-lived access tokens in Home Assistant).
"""

from __future__ import annotations

import httpx


class HAError(RuntimeError):
    """Raised when Home Assistant is unreachable or rejects the request."""


def _base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def check(base_url: str, token: str) -> dict:
    """Verify the URL/token and return the HA version + location name."""
    base = _base(base_url)
    if not base or not token:
        raise HAError("Home Assistant URL and token are required")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            api = await client.get(f"{base}/api/", headers=_headers(token))
            if api.status_code == 401:
                raise HAError("Invalid token (401)")
            api.raise_for_status()
            cfg = await client.get(f"{base}/api/config", headers=_headers(token))
            cfg.raise_for_status()
            data = cfg.json()
    except HAError:
        raise
    except Exception as exc:
        raise HAError(f"Could not reach Home Assistant: {exc}") from exc
    return {
        "connected": True,
        "version": data.get("version", ""),
        "location_name": data.get("location_name", ""),
    }


def parse_update_entity(state: dict) -> dict:
    attrs = state.get("attributes", {})
    entity_id = state.get("entity_id", "")
    return {
        "entity_id": entity_id,
        "title": attrs.get("title") or attrs.get("friendly_name") or entity_id,
        "friendly_name": attrs.get("friendly_name", ""),
        "installed_version": attrs.get("installed_version"),
        "latest_version": attrs.get("latest_version"),
        "update_available": state.get("state") == "on",
        "release_summary": (attrs.get("release_summary") or "")[:300],
        "release_url": attrs.get("release_url"),
    }


async def get_updates(base_url: str, token: str) -> dict:
    """Return HA ``update.*`` entities, split into available vs up-to-date."""
    base = _base(base_url)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base}/api/states", headers=_headers(token))
            if resp.status_code == 401:
                raise HAError("Invalid token (401)")
            resp.raise_for_status()
            states = resp.json()
    except HAError:
        raise
    except Exception as exc:
        raise HAError(f"Could not reach Home Assistant: {exc}") from exc

    entities = [
        parse_update_entity(s) for s in states if str(s.get("entity_id", "")).startswith("update.")
    ]
    available = [e for e in entities if e["update_available"]]
    return {
        "total": len(entities),
        "available": available,
        "up_to_date": len(entities) - len(available),
    }


async def install_update(base_url: str, token: str, entity_id: str) -> dict:
    """Trigger HA's ``update.install`` service for an update entity."""
    base = _base(base_url)
    if not entity_id.startswith("update."):
        raise HAError("Not an update entity")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/api/services/update/install",
                headers=_headers(token),
                json={"entity_id": entity_id},
            )
            resp.raise_for_status()
    except Exception as exc:
        raise HAError(f"Install failed: {exc}") from exc
    return {"status": "install_started", "entity_id": entity_id}
