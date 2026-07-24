"""The SPA static server must tell WebView2 to revalidate.

WebView2 keeps a persistent HTTP cache across app updates. Without Cache-Control
it heuristically caches index.html and serves the OLD UI after an upgrade (while
the backend reports the new version). _RevalidatingStatic must send no-cache so
the current index.html + its new hashed JS always load.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.main import _RevalidatingStatic


def test_static_sends_no_cache_on_html_and_assets(tmp_path):
    (tmp_path / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")

    app = Starlette()
    app.mount("/", _RevalidatingStatic(directory=str(tmp_path), html=True), name="frontend")
    client = TestClient(app)

    # index.html served at "/" must not be cached without revalidation.
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"

    # hashed assets too (revalidate → cheap 304, never a stale UI).
    r2 = client.get("/assets/index-abc123.js")
    assert r2.status_code == 200
    assert r2.headers.get("cache-control") == "no-cache"
