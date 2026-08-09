"""Rebuild the bundled OUI table from the authoritative IEEE MA-L registry.

Run this to refresh ``app/data/oui.json.gz``:

    python tools/build_oui.py            # downloads the live registry
    python tools/build_oui.py oui.csv    # or uses a CSV you already have

Why a generator instead of a hand-maintained table: the curated list this replaces held
287 prefixes, and on the first real network it was measured against it named **0 of 15**
manufacturers — every device showed as "unknown" with no name. 287 entries cannot cover
a registry of 39,000; the answer is not a longer hand-list, it is the registry.

Two rules from the earlier audit are kept, because they are what make the table honest:
  * only MA-L (24-bit) assignments — our prefixes are six hex digits, and an MA-M/MA-S
    prefix would attribute a shared block to one company;
  * a block held by "IEEE Registration Authority" is subdivided among MA-M/MA-S owners
    and has NO single vendor, so it is dropped rather than attributed.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REGISTRY_URL = "https://standards-oui.ieee.org/oui/oui.csv"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "oui.json.gz"

# Legal suffixes carry no information for someone reading a list of devices, and they
# cost bytes in a file we ship. "Samsung Electronics Co., Ltd." reads as "Samsung".
_SUFFIX = re.compile(
    r"[,\s]+(Co\.?,?\s*Ltd\.?|Ltd\.?|LTD|Limited|Inc\.?|INC|LLC|L\.L\.C\.|Corp\.?|"
    r"Corporation|GmbH|S\.A\.?|SAS|S\.p\.A\.|B\.V\.|N\.V\.|A/S|AB|AG|Oy|Pty|PLC|"
    r"Co\.?|Company|Technologies|Technology|Electronics|Electronic|International)\.?$",
    re.I,
)


def tidy(name: str) -> str:
    n = _SUFFIX.sub("", name.strip().strip('"'))
    n = re.sub(r"\s+", " ", n).strip(" .,-")
    return n or name.strip()


def build(rows: list[dict]) -> dict[str, str]:
    table: dict[str, str] = {}
    for row in rows:
        prefix = (row.get("Assignment") or "").strip().upper()
        org = (row.get("Organization Name") or "").strip()
        if len(prefix) != 6 or not org:
            continue
        if org.lower().startswith("ieee registration authority"):
            continue  # a subdivided block: no single owner to name
        if org.lower() in ("private", "n/a", "none"):
            continue
        table[prefix] = tidy(org)
    return table


def main() -> int:
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
        source = sys.argv[1]
    else:
        print(f"downloading {REGISTRY_URL} ...")
        with urllib.request.urlopen(REGISTRY_URL, timeout=300) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
        source = REGISTRY_URL

    rows = list(csv.DictReader(io.StringIO(text)))
    table = build(rows)
    if len(table) < 30_000:
        print(f"REFUSING: only {len(table)} prefixes parsed — the registry looks truncated")
        return 1

    payload = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(gzip.compress(payload, 9))
    print(
        f"{len(rows)} assignments -> {len(table)} prefixes\n"
        f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB gzipped, "
        f"{len(payload) / 1024:.0f} KB raw)\n"
        f"source: {source}  at {datetime.now(UTC):%Y-%m-%d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
