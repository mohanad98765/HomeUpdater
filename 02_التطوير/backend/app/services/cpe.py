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
    "WinAppRuntime.Main.1.8": (
        "winget reports the whole MSIX identity in the version column"
        " ('MSIX\\\\MicrosoftCorporationII.WinAppRuntime.Main.1.8_8000.921.1539.0_x64…'),"
        " and windows_app is the Remote Desktop client, not the App SDK."
    ),
}

# Registry-discovered products are keyed by an ARP id that embeds a per-version MSI
# GUID, so exclusions for them are keyed by DISPLAY NAME instead. Same contract as
# UNMAPPABLE: every line says what was checked in NVD's CPE dictionary and why the
# product still cannot be matched. Verified 2026-07-25.
UNMAPPABLE_NAMES: dict[str, str] = {
    "MSI Afterburner 4.6.7 Beta 2": (
        "cpe:2.3:a:msi:afterburner exists, but the reported version '4.6.7 Beta 2' is"
        " not a comparable number — a pre-release tag cannot be ordered against NVD."
    ),
    "uTorrent Web": (
        "Only an unversioned cpe:2.3:a:utorrent:web entry exists (version field '-'),"
        " so every record would match every build — indicative, never precise."
    ),
    "Microsoft 365 - ar-sa": (
        "cpe:2.3:a:microsoft:365_apps numbers releases as 2401.17231.20236 (Click-to-Run"
        " channel), while the install reports 16.0.20131.20154 — two different schemes."
    ),
    "Windows Software Development Kit - Windows 10.0.26100.8249": (
        "cpe:2.3:a:microsoft:windows_software_development_kit uses 10.0.26100.x; the"
        " registry reports 10.1.26100.8249, and rewriting 10.1 -> 10.0 would be a guess."
    ),
    "Windows SDK AddOn": "No CPE for the SDK add-on; its 10.1.0.0 is not an SDK build number.",
    "Microsoft Visual Studio Installer": "No CPE exists for the installer component (searched).",
    "Microsoft Teams Meeting Add-in for Microsoft Office": (
        "No CPE for the Office add-in (searched 'teams meeting': 0 results)."
    ),
    "NVIDIA App 11.0.8.299": (
        "The nvidia:install_application / *_runtime_environment entries are different"
        " products; no CPE covers the NVIDIA App control panel."
    ),
    "NVIDIA FrameView SDK 1.8.12612.38276700": "No CPE exists (searched 'frameview': 0 results).",
    "NVIDIA برنامج تشغيل صوت HD 1.4.5.7": (
        "The HD Audio driver ships with the graphics package but has no CPE of its own;"
        " nvidia:gpu_display_driver covers the display driver, not this component."
    ),
    "Wifi6 802.11ax USB Adapter version 4.0.0.2": (
        "An OEM adapter driver with no vendor string to search on and no CPE."
    ),
    "فحص حالة كمبيوتر بنظام Windows": (
        "PC Health Check: no CPE exists (searched 'pc health check': 0 results)."
    ),
    "HomeUpdater 1.10.6": "This application itself — no CPE, and self-reporting would be circular.",
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


@dataclass(frozen=True)
class FallbackRule:
    """Match a product that has no stable id — by display name, or by id suffix.

    winget ids are stable, so ``CPE_MAP`` keys on them. Products discovered through
    the Windows registry (``ARP\\Machine\\...``) are not: for MSI installers the id
    embeds the ProductCode GUID, which **changes with every version** (measured:
    Node.js), so a mapping keyed on it would silently stop matching after the next
    update — the worst kind of failure, because coverage would drop with no error.
    ``kind="name"`` matches the display name (anchored regex, case-insensitive) and
    ``kind="id_suffix"`` matches the tail of the id (for vendors whose GUID is fixed
    and whose component is identified by the suffix, and whose display name is
    localized — NVIDIA's driver is "برنامج تشغيل الرسومات" on this machine).
    """

    kind: str
    pattern: str
    entry: CpeEntry


# Every rule below was checked against NVD's CPE dictionary; the note says what was
# found, so a future reader can re-verify instead of trusting the line.
FALLBACK_RULES: tuple[FallbackRule, ...] = (
    # cpe:2.3:a:nodejs:node.js — 1658 dictionary entries, versions 0.10.x … 24.x.
    FallbackRule("name", r"^node\.js$", CpeEntry("nodejs", "node.js", version_parts=3)),
    # cpe:2.3:a:usbpcap_project:usbpcap — 20 entries; 1.5.4.0 (this build) is one.
    FallbackRule("name", r"^usbpcap\b", CpeEntry("usbpcap_project", "usbpcap", version_parts=4)),
    # cpe:2.3:a:nmap:npcap — the dictionary holds only 0.992, so an install of 1.88
    # legitimately matches nothing today; the vendor/product pair is right, and a
    # future range-based record will apply.
    FallbackRule(
        "name",
        r"^npcap$",
        CpeEntry("nmap", "npcap", caveat="NVD's dictionary lists only npcap 0.992"),
    ),
    # cpe:2.3:a:devolutions:unigetui — titles read "Devolutions UniGetUI 2026.2.1.0",
    # same 2026.x numbering as the install; medium because the vendor string is the
    # sponsor, not the original author.
    FallbackRule(
        "name",
        r"^unigetui$",
        CpeEntry(
            "devolutions",
            "unigetui",
            version_parts=4,
            confidence="medium",
            caveat="NVD lists UniGetUI under the vendor 'devolutions'",
        ),
    ),
    # cpe:2.3:a:nvidia:gpu_display_driver — many versions (390.x … 5xx); the id
    # suffix is used because the display name is localized. No 6xx entries exist
    # yet, so a 610.74 install matches only range-based records — correct, not blind.
    FallbackRule(
        "id_suffix",
        "_display.driver",
        CpeEntry(
            "nvidia",
            "gpu_display_driver",
            caveat="NVD has no 6xx driver entries yet; only ranged records can match",
        ),
    ),
)


def _fallback_entry(product_id: str, name: str) -> CpeEntry | None:
    pid = (product_id or "").lower()
    nm = (name or "").strip()
    for rule in FALLBACK_RULES:
        if rule.kind == "id_suffix":
            if pid.endswith(rule.pattern):
                return rule.entry
        elif re.search(rule.pattern, nm, re.IGNORECASE):
            return rule.entry
    return None


def resolve(product_id: str, raw_version: str, name: str = "") -> CpeIdentity | None:
    """Map an installed product to a CPE identity, or ``None`` if we can't.

    ``None`` means one of: the product isn't in the curated map, or its version
    isn't comparable. Both are reported honestly as "not precisely matched".
    """
    entry = CPE_MAP.get(product_id) or _fallback_entry(product_id, name)
    if entry is None:
        return None
    version = normalize_version(raw_version)
    if version is None:
        return None
    if entry.version_parts:
        version = _fit_parts(version, entry.version_parts)
    return CpeIdentity(vendor=entry.vendor, product=entry.product, version=version)


def entry_for(product_id: str, name: str = "") -> CpeEntry | None:
    """The curated entry (confidence + caveat) so the UI/report can show them."""
    return CPE_MAP.get(product_id) or _fallback_entry(product_id, name)


def exclusion_detail(product_id: str, name: str = "") -> str:
    """The documented reason a product cannot be matched — id-keyed or name-keyed."""
    return UNMAPPABLE.get(product_id) or UNMAPPABLE_NAMES.get((name or "").strip(), "")


def unmatched_reason(product_id: str, raw_version: str, name: str = "") -> str:
    """Why this product produced no CPE identity — specific enough to act on.

    ``no_cpe_mapping`` used to be returned for every case, which lumped "we looked
    and NVD has nothing" together with "nobody has looked yet" and with the 57 Store
    packages NVD does not track. Those need different answers from the reader.
    """
    if CPE_MAP.get(product_id) or _fallback_entry(product_id, name):
        return "version_not_comparable"
    kind = classify_unmapped(product_id, name)
    if kind in ("documented_exclusion", "store_package"):
        return kind
    return "no_cpe_mapping"


def classify_unmapped(product_id: str, name: str = "") -> str:
    """WHY a product is not precisely matchable — the honest denominator.

    Measured on a real Windows 11 machine: 95 of 115 inventoried products had no
    CPE mapping, but 57 of those are **Microsoft Store / inbox packages** whose
    version is a package-identity number (``11.2605.9.0`` for the Calculator) that
    NVD does not track at all, and 19 more are documented traps. Reporting one flat
    "17% coverage" invited the wrong conclusion — that the curated map is lazy —
    when the real answer is that most of the estate is not addressable by CPE.
    Only ``not_investigated`` is a gap that more work can close.
    """
    if product_id in CPE_MAP or _fallback_entry(product_id, name) is not None:
        return "mapped"
    if product_id in UNMAPPABLE or name.strip() in UNMAPPABLE_NAMES:
        return "documented_exclusion"
    if product_id.startswith("MSIX" + "\\") or product_id.startswith("MSIX/"):
        return "store_package"
    return "not_investigated"


def coverage(products: list[tuple[str, str]] | list[str]) -> dict:
    """How much of an inventory the curated map can precisely match.

    Surfaced to the UI/report so the gap is visible instead of implied: a report
    that silently covers 30% of an estate is worse than one that says so. The raw
    ``percent`` stays the headline — the breakdown explains it, it does not replace
    it, and ``addressable_percent`` is reported next to it, never instead of it.

    Accepts ``(product_id, name)`` pairs; a bare list of ids still works, but then
    the name-based rules cannot apply and coverage reads lower than reality.
    """
    pairs = [(p, "") if isinstance(p, str) else (p[0], p[1] or "") for p in products]
    total = len(pairs)
    buckets = {"mapped": 0, "documented_exclusion": 0, "store_package": 0, "not_investigated": 0}
    for pid, nm in pairs:
        buckets[classify_unmapped(pid, nm)] += 1
    mapped = buckets["mapped"]
    addressable = mapped + buckets["not_investigated"]
    return {
        "total": total,
        "mapped": mapped,
        "unmapped": total - mapped,
        "percent": round(100.0 * mapped / total, 1) if total else 0.0,
        # Of the products a CPE mapping could ever cover, how many are covered.
        "addressable_total": addressable,
        "addressable_percent": round(100.0 * mapped / addressable, 1) if addressable else 0.0,
        "by_reason": buckets,
    }
