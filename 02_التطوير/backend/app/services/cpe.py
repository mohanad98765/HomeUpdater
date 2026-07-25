"""CPE identity for installed products — the input to PRECISE CVE matching.

Why this exists: ``cve.py`` asks NVD for a *vendor keyword*, which is why the
security page can only claim "indicative exposure". A vendor keyword cannot tell
whether the installed version is actually affected, so it produces both false
positives and false negatives. NVD's real matching key is a **CPE 2.3 name**
(``cpe:2.3:a:vendor:product:version:...``), and to build one we need three things:
the vendor, the product, and a comparable version.

Two deliberate design rules, because the output is meant to become audit-grade:

1. **A curated map, never a guessed one.** ``CPE_MAP`` holds only entries verified
   against the NVD CPE dictionary. An unmapped product returns ``None`` and is
   reported as *not matched* — it is never silently keyword-matched and presented
   as a precise finding.
2. **A version we can compare, or nothing.** Real ``winget list`` output contains
   version strings that are not versions at all: ``"ad 9.7.11"`` (AnyDesk prefixes
   its build), ``"> 3.13.5"`` (winget's "unknown, at least" marker), and one entry
   whose whole MSIX identity lands in the version column. Feeding those to NVD
   would silently match the wrong thing, so ``normalize_version`` extracts a
   dotted numeric core and refuses anything ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# The curated table: winget package Id -> (CPE vendor, CPE product)
#
# Every entry is verified against the NVD CPE dictionary. Products that have no
# meaningful application CPE (Microsoft runtimes and redistributables, whose
# advisories ride on Windows/Visual Studio rather than a product of their own)
# are deliberately ABSENT rather than mapped to something close-looking.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CpeEntry:
    """A curated mapping. ``version_parts`` trims/pads the reported version to the
    number of segments NVD actually uses for that product — Git for Windows reports
    ``2.55.0.3`` while NVD tracks upstream ``2.55.0``, and without the trim the query
    silently matches nothing, which a report would render as "no vulnerabilities"."""

    vendor: str
    product: str
    version_parts: int | None = None
    confidence: str = "high"  # high | medium — surfaced so a reader can weigh it
    caveat: str = ""


CPE_MAP: dict[str, CpeEntry] = {
    # --- exact scheme match, installed version enumerated in the dictionary ---
    "7zip.7zip": CpeEntry("7-zip", "7-zip"),
    "Google.Chrome": CpeEntry("google", "chrome"),  # needs the full 4-part build
    "Microsoft.Edge": CpeEntry(
        "microsoft",
        "edge_chromium",  # NOT microsoft:edge — that product is the legacy EdgeHTML
        caveat="Chromium Edge lives under edge_chromium; legacy microsoft:edge is sparse.",
    ),
    "WiresharkFoundation.Wireshark": CpeEntry("wireshark", "wireshark"),
    "Insecure.Nmap": CpeEntry(
        "nmap", "nmap", caveat="Bundled Npcap/OpenSSL have their own CPEs and are not covered."
    ),
    "Microsoft.VisualStudioCode": CpeEntry("microsoft", "visual_studio_code"),
    "Microsoft.WindowsTerminal": CpeEntry("microsoft", "terminal"),  # not windows_terminal
    "Ollama.Ollama": CpeEntry("ollama", "ollama"),
    "Tailscale.Tailscale": CpeEntry(
        "tailscale", "tailscale", caveat="Some Tailscale CVEs are non-Windows clients."
    ),
    "Cloudflare.cloudflared": CpeEntry("cloudflare", "cloudflared"),
    "Python.Python.3.14": CpeEntry("python", "python"),
    "GitHub.cli": CpeEntry("github", "cli", version_parts=3),
    "AnyDesk.AnyDesk": CpeEntry("anydesk", "anydesk"),
    "Gyan.FFmpeg": CpeEntry(
        "ffmpeg",
        "ffmpeg",
        confidence="medium",
        caveat="Upstream CVEs incl. bundled libav*; Gyan git/nightly builds are not matchable.",
    ),
    "Adobe.Acrobat.Reader.64-bit": CpeEntry(
        "adobe",
        "acrobat_reader_dc",
        confidence="medium",
        caveat="Continuous track is split with adobe:acrobat_reader; the full build is required.",
    ),
    "JRSoftware.InnoSetup": CpeEntry(
        "jrsoftware",
        "inno_setup",
        confidence="medium",
        caveat="Most Inno Setup CVEs concern GENERATED installers, not the installed IDE.",
    ),
    "Microsoft.AppInstaller": CpeEntry(
        "microsoft",
        "app_installer",
        confidence="medium",
        caveat="Range-criteria only (no dictionary entries), so only ranged CVEs resolve.",
    ),
    # --- version needs trimming to the segments NVD tracks -------------------
    "Git.Git": CpeEntry(
        "git",
        "git",
        version_parts=3,  # 2.55.0.3 (Git-for-Windows revision) -> upstream 2.55.0
        confidence="medium",
        caveat="Git-for-Windows revision suffix trimmed to the upstream 3-part version.",
    ),
    "Microsoft.WSL": CpeEntry("microsoft", "windows_subsystem_for_linux", version_parts=3),
    "GlavSoft.TightVNC": CpeEntry(
        "tightvnc",
        "tightvnc",
        version_parts=3,
        confidence="medium",
        caveat="Dictionary has only 5 entries; empty results mean NO DATA, not 'clean'.",
    ),
}

# Deliberately NOT mapped, with the reason — so nobody "helpfully" adds a plausible
# guess later. Each of these was investigated against the NVD CPE dictionary and
# either has no application CPE, or one whose versioning cannot be compared to what
# winget reports. Both cases are reported as "no NVD coverage", never as "clean".
UNMAPPABLE: dict[str, str] = {
    "Microsoft.VisualStudio.BuildTools": (
        "CPE holds one version (17.13.7) + target_sw=visual_studio; an 18.x install"
        " matches nothing."
    ),
    "Microsoft.Teams": "Installed build 26183 vs NVD 1.6.00.x / 7.x — no comparable scheme.",
    "Microsoft.PowerBI": (
        "Every versioned CPE entry is mobile (android/iphone_os); the 2.2.x prefix can"
        " collide with Desktop 2.156.x."
    ),
    "Microsoft.OneDrive": (
        "Only the version-less entry targets Windows; versioned rows are" " macOS/Android/iOS."
    ),
    "Anthropic.Claude": (
        "NVD uses 1.<4-digit>.0 while the install reports 1.24012 — not comparable."
    ),
    "Nvidia.PhysX": (
        "Three ancient entries mixing two schemes; 9.23 matches nothing and sorts wrong."
    ),
    "Guru3D.RTSS": "No product exists under any plausible vendor name.",
    "REALiX.HWiNFO": (
        "Only a CPE for the bundled kernel driver, whose version is not the app version."
    ),
    "Microsoft.VCRedist.2015+.x64": "Legacy microsoft:visual_c++ covers 2005/2008/2010 only.",
    "Microsoft.VCRedist.2015+.x86": "Legacy microsoft:visual_c++ covers 2005/2008/2010 only.",
    "Microsoft.VCLibs.14": "No vclibs product; UWP framework serviced via Windows/VS advisories.",
    "Microsoft.VCLibs.Desktop.14": "Same as VCLibs.14 — no application CPE.",
    "Microsoft.DotNet.Native.Runtime": "No .NET Native product; microsoft:.net 2.x would collide.",
    "Microsoft.WindowsAppRuntime.1.6": (
        "microsoft:windows_app is the REMOTE DESKTOP client, not the App SDK."
    ),
    "Microsoft.WindowsAppRuntime.1.7": (
        "microsoft:windows_app is the REMOTE DESKTOP client, not the App SDK."
    ),
    "Microsoft.WindowsAppRuntime.1.8": (
        "microsoft:windows_app is the REMOTE DESKTOP client, not the App SDK."
    ),
    "Microsoft.WindowsInstallationAssistant": (
        "No application CPE; a Windows OS CPE would flood the report."
    ),
    "Microsoft.UI.Xaml.2.8": "No WinUI/UI.Xaml product (winui hits are Telerik).",
    "Python.Launcher": (
        "No distinct product; mapping to python:python would duplicate every finding."
    ),
}


@dataclass(frozen=True)
class CpeIdentity:
    """A resolved CPE for one installed product."""

    vendor: str
    product: str
    version: str

    @property
    def cpe_name(self) -> str:
        """The CPE 2.3 name NVD expects in its ``cpeName`` query parameter."""
        return f"cpe:2.3:a:{self.vendor}:{self.product}:{self.version}:*:*:*:*:*:*:*"


# A comparable version is a dotted numeric run: 1, 1.2, 1.2.3, 1.2.3.4
_VERSION_RE = re.compile(r"^\d+(?:\.\d+){0,3}$")
# Markers winget uses when it does NOT actually know the installed version.
_UNKNOWN_MARKERS = ("unknown", "<", ">")


def normalize_version(raw: str) -> str | None:
    """Return a comparable dotted version, or ``None`` when it isn't one.

    ``None`` is a first-class answer: the caller must then report the product as
    unmatched instead of querying NVD with something meaningless.

    Handled real cases (all observed in live ``winget list`` output):
      ``"26.02"``          -> ``"26.02"``
      ``"ad 9.7.11"``      -> ``"9.7.11"``   (a single stray token before it)
      ``"> 3.13.5"``       -> ``None``       (winget's "at least" marker)
      ``"MSIX\\... 8000.921.1539.0"`` -> ``None`` (identity leaked into the column)
    """
    if not raw:
        return None
    text = raw.strip()
    low = text.lower()
    if any(m in low for m in _UNKNOWN_MARKERS):
        return None
    if _VERSION_RE.match(text):
        return text

    # Allow exactly one SHORT ALPHABETIC leading token (e.g. AnyDesk's "ad 9.7.11").
    # The narrowness is deliberate: a permissive rule accepted
    # "MSIX\\…WinAppRuntime.Main.1.8_8000.921.1539.0_x64 8000.921.1539.0" and would
    # have matched a package identity's trailing number as if it were a product
    # version — a wrong precise finding, which is the one thing this path must not
    # produce.
    parts = text.split()
    if len(parts) == 2 and parts[0].isalpha() and len(parts[0]) <= 8:
        if _VERSION_RE.match(parts[1]):
            return parts[1]
    return None


def _fit_parts(version: str, parts: int) -> str:
    """Trim or pad a dotted version to exactly ``parts`` segments."""
    seg = version.split(".")
    if len(seg) > parts:
        return ".".join(seg[:parts])
    return ".".join(seg + ["0"] * (parts - len(seg)))


def resolve(product_id: str, raw_version: str) -> CpeIdentity | None:
    """Map an installed product to a CPE identity, or ``None`` if we can't.

    ``None`` means one of: the product isn't in the curated map, or its version
    isn't comparable. Both are reported honestly as "not precisely matched".
    """
    entry = CPE_MAP.get(product_id)
    if entry is None:
        return None
    version = normalize_version(raw_version)
    if version is None:
        return None
    if entry.version_parts:
        version = _fit_parts(version, entry.version_parts)
    return CpeIdentity(vendor=entry.vendor, product=entry.product, version=version)


def entry_for(product_id: str) -> CpeEntry | None:
    """The curated entry (confidence + caveat) so the UI/report can show them."""
    return CPE_MAP.get(product_id)


def coverage(product_ids: list[str]) -> dict:
    """How much of an inventory the curated map can precisely match.

    Surfaced to the UI/report so the gap is visible instead of implied: a report
    that silently covers 30% of an estate is worse than one that says so.
    """
    total = len(product_ids)
    mapped = sum(1 for pid in product_ids if pid in CPE_MAP)
    return {
        "total": total,
        "mapped": mapped,
        "unmapped": total - mapped,
        "percent": round(100.0 * mapped / total, 1) if total else 0.0,
    }
