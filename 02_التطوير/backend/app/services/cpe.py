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
    # "vendor" = verified by us and shipped in this table · "site" = added on the
    # customer's machine through cpe_overrides.json. The pack prints it, because a
    # customer's mapping must not appear with our authority.
    source: str = "vendor"


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
    # --- software a paying customer runs (added v1.13.0) ---------------------
    # Every entry below was decided from a live pull of NVD's CPE dictionary, then
    # attacked by a second reviewer before being accepted. version_parts is left
    # unset wherever NVD's own segment count varies for that product — pinning it
    # would corrupt one of the shapes NVD actually stores.
    "Mozilla.Firefox": CpeEntry(
        "mozilla",
        "firefox",
        caveat="1132 dictionary entries; ESR builds report '…esr' and are refused rather"
        " than mis-matched.",
    ),
    "Mozilla.Thunderbird": CpeEntry(
        "mozilla",
        "thunderbird",
        confidence="medium",
        caveat="601 entries, but the sampled versions are the early line — an empty result"
        " for a current build means NO DATA, not clean.",
    ),
    "TheDocumentFoundation.LibreOffice": CpeEntry(
        "libreoffice",  # NOT documentfoundation — that is the winget publisher
        "libreoffice",
        confidence="medium",
        caveat="Dictionary mixes 3- and 4-segment versions (3.5.2 alongside 3.5.4.2), so a"
        " release recorded with the other shape matches nothing.",
    ),
    "VideoLAN.VLC": CpeEntry(
        "videolan",
        "vlc_media_player",
        caveat="Old entries carry letter suffixes (0.8.6b) that are refused, not guessed.",
    ),
    "RARLab.WinRAR": CpeEntry(
        "rarlab",
        "winrar",
        confidence="medium",
        caveat="NVD writes WinRAR as a zero-padded 2-segment number (7.13, 4.00) and holds"
        " both '4.10' and '4.1.0' for one release.",
    ),
    "Notepad++.Notepad++": CpeEntry(
        "don_ho",  # the CPE vendor is the author, not 'notepad-plus-plus'
        "notepad++",
        confidence="medium",
        caveat="60 entries under vendor don_ho; the sampled versions are the 2.x-3.x era, so"
        " a current build may resolve only through ranged records.",
    ),
    "PuTTY.PuTTY": CpeEntry(
        "putty",
        "putty",
        confidence="medium",
        caveat="NVD uses TWO segments (0.83); an install reporting 0.83.0.0 matches nothing"
        " — a miss, never a false hit.",
    ),
    "TimKosse.FileZilla.Client": CpeEntry(
        "filezilla-project",  # hyphenated vendor, and the CLIENT product, not the server
        "filezilla_client",
        caveat="Release candidates are separate rows; sample ceiling is 3.49.1.",
    ),
    "Microsoft.PowerToys": CpeEntry(
        "microsoft",
        "powertoys",
        caveat="A Store/MSIX PowerToys install carries a package identity instead and is"
        " classified as a store package, not by this entry.",
    ),
    "Telegram.TelegramDesktop": CpeEntry(
        "telegram",
        "telegram_desktop",
        caveat="Desktop client only; the mobile clients are separate NVD products.",
    ),
    "Postman.Postman": CpeEntry(
        "postman",
        "postman",
        confidence="medium",
        caveat="GA releases appear as 2 segments (10.12) and patches as 3, so an exact-version"
        " query hits at most one of the two forms.",
    ),
    "Audacity.Audacity": CpeEntry(
        "audacityteam",
        "audacity",
        confidence="medium",
        caveat="Sample stops at 2.0.5; whether the 3.x line is enumerated is unverified.",
    ),
    "GIMP.GIMP": CpeEntry(
        "gimp",
        "gimp",
        confidence="medium",
        caveat="232 entries; segment count varies across the 2.x line.",
    ),
    "Malwarebytes.Malwarebytes": CpeEntry(
        "malwarebytes",
        "malwarebytes",
        confidence="medium",
        caveat="49 entries and one unversioned row; the product was renamed across versions.",
    ),
    "TeamViewer.TeamViewer": CpeEntry(
        "teamviewer",
        "teamviewer",
        confidence="medium",
        caveat="67 entries mixing 2-segment (15.28) and long build forms (10.0.134865).",
    ),
    "Zoom.Zoom": CpeEntry(
        # NOT zoom:zoom — the keyword probe showed the desktop client lives under
        # zoom:workplace_desktop with current 6.x versions, while zoom:workplace is the
        # mobile line and workplace_virtual_desktop_infrastructure is the VDI plugin.
        "zoom",
        "workplace_desktop",
        confidence="medium",
        caveat="Desktop line (6.x enumerated); the mobile and VDI products are separate CPEs.",
    ),
    "PostgreSQL.PostgreSQL": CpeEntry(
        "postgresql",
        "postgresql",
        confidence="medium",
        caveat="595 entries spanning 6.x to current; one unversioned row can never match.",
    ),
    "Oracle.MySQL": CpeEntry(
        "oracle",
        "mysql",
        confidence="medium",
        caveat="776 entries; MySQL Server and Connector CVEs share this product, so a finding"
        " may concern a component that is not installed.",
    ),
    "Docker.DockerDesktop": CpeEntry(
        "docker",
        "docker_desktop",
        confidence="medium",
        caveat="143 entries with 4-segment versions (4.28.0.1); a 3-segment report may miss.",
    ),
    "EclipseAdoptium.Temurin.21.JRE": CpeEntry(
        "eclipse",
        "temurin",
        confidence="medium",
        caveat="Lengths vary (11.0.12 vs 11.0.12.1); Temurin only — other JDK builds have"
        " their own CPEs.",
    ),
    "Google.Drive": CpeEntry(
        "google",
        "drive",
        confidence="medium",
        caveat="The dictionary mixes the modern desktop line (26.1, 30.1) with legacy"
        " 1.0.x builds and one unversioned row.",
    ),
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
    # --- business software checked and deliberately NOT mapped (v1.13.0) -----
    # Each line says what the dictionary actually returned, so the claim is checkable.
    "SlackTechnologies.Slack": (
        "Keyword 'slack' returns 304 rows and NONE is the Slack desktop app (Jenkins"
        " plugin, ArchiveBot, Slackware Linux). No product to map."
    ),
    "OBSProject.OBSStudio": (
        "Both cpe:2.3:a:obsproject:obs_studio and the keyword 'obs studio' return 0 —"
        " OBS Studio is absent from the dictionary."
    ),
    "Discord.Discord": (
        "Only 2 rows exist: one unversioned and one 0.0.291, so any current build either"
        " matches nothing or matches an unbounded record."
    ),
    "Valve.Steam": (
        "valvesoftware:steam_client mixes a Unix timestamp (1528829181), dates"
        " (2018-03-22) and 2.10.91.91 in the version field — not orderable."
    ),
    "Microsoft.SQLServer.2022.Developer": (
        "microsoft:sql_server versions are release years (2000, 2005, 2012) plus service"
        " packs, while the install reports 16.0.x — no comparable scheme."
    ),
    "Microsoft.VisualStudio.2022.Community": (
        "microsoft:visual_studio_2022 enumerates 17.x releases, but a VS install reports"
        " its own build (17.14.36301.6) whose 3rd/4th segments do not exist in NVD."
    ),
    "Oracle.JavaRuntimeEnvironment": (
        "oracle:jre holds 525 rows with only three distinct version fields (1.4.2_38,"
        " 1.4.2_40, 1.7.0); modern 8u/17 builds are recorded under other products."
    ),
    "Microsoft.Skype": (
        "Only 8 rows, mostly unversioned, for a retired desktop line — a match would be"
        " an unbounded record, not evidence about this build."
    ),
    "Dropbox.Dropbox": (
        "dropbox:dropbox stops at the 2.3.x era (31 rows) while the client reports 2xx.y.z;"
        " mapping it would report 'no findings' for a version NVD never covered."
    ),
    "WinAppRuntime.Main.1.8": (
        "winget reports the whole MSIX identity in the version column"
        " ('MSIX\\\\MicrosoftCorporationII.WinAppRuntime.Main.1.8_8000.921.1539.0_x64…'),"
        " and windows_app is the Remote Desktop client, not the App SDK."
    ),
}


# Registry-discovered products have no stable id (the ARP key embeds a per-version
# MSI GUID), so their exclusions are keyed by DISPLAY NAME — and the pattern must be
# version-AGNOSTIC. v1.11.0 shipped these as exact names, which broke the moment this
# machine upgraded: the entry "HomeUpdater 1.10.6" stopped matching "HomeUpdater
# 1.11.0" and the product silently fell back to "not investigated" in the report.
# Anchored prefixes fix that; ``sample`` records a real observed name so a test can
# bump its version and prove the classification does not move.
# Same contract as UNMAPPABLE: each reason states what was checked in NVD's CPE
# dictionary. Verified 2026-07-25.
@dataclass(frozen=True)
class ExclusionRule:
    kind: str  # "name" (anchored regex) | "id_suffix" (lowercase literal)
    pattern: str
    reason: str
    sample: str = ""


EXCLUSION_RULES: tuple[ExclusionRule, ...] = (
    ExclusionRule(
        # Our own AppId, pinned in the Inno script ("do NOT change between releases"),
        # so this is stable in a way the display name never was.
        "id_suffix",
        "{8f3a1c7e-2b4d-4e6a-9c1f-5d7e8a9b0c1d}_is1",
        "This application itself — no CPE, and self-reporting would be circular.",
        sample="ARP"
        + chr(92)
        + "Machine"
        + chr(92)
        + "X64"
        + chr(92)
        + "{8F3A1C7E-2B4D-4E6A-9C1F-5D7E8A9B0C1D}_is1",
    ),
    ExclusionRule(
        "name",
        r"^msi afterburner\b",
        "cpe:2.3:a:msi:afterburner exists, but the reported version carries a"
        " pre-release tag ('4.6.7 Beta 2') that cannot be ordered against NVD.",
        sample="MSI Afterburner 4.6.7 Beta 2",
    ),
    ExclusionRule(
        "name",
        r"^utorrent web\b",
        "Only an unversioned cpe:2.3:a:utorrent:web entry exists (version field '-'),"
        " so every record would match every build — indicative, never precise.",
        sample="uTorrent Web",
    ),
    ExclusionRule(
        "name",
        r"^microsoft 365\b",
        "cpe:2.3:a:microsoft:365_apps numbers releases as 2401.17231.20236 (Click-to-Run"
        " channel), while the install reports 16.0.x — two different schemes.",
        sample="Microsoft 365 - ar-sa",
    ),
    ExclusionRule(
        "name",
        r"^windows software development kit\b",
        "cpe:2.3:a:microsoft:windows_software_development_kit uses 10.0.26100.x; the"
        " registry reports 10.1.26100.x, and rewriting 10.1 -> 10.0 would be a guess.",
        sample="Windows Software Development Kit - Windows 10.0.26100.8249",
    ),
    ExclusionRule(
        "name",
        r"^windows sdk addon\b",
        "No CPE for the SDK add-on; its 10.1.0.0 is not an SDK build number.",
        sample="Windows SDK AddOn",
    ),
    ExclusionRule(
        "name",
        r"^microsoft visual studio installer\b",
        "No CPE exists for the Visual Studio installer component (searched).",
        sample="Microsoft Visual Studio Installer",
    ),
    ExclusionRule(
        "name",
        r"^microsoft teams meeting add-?in\b",
        "No CPE for the Office add-in (searched 'teams meeting': 0 results).",
        sample="Microsoft Teams Meeting Add-in for Microsoft Office",
    ),
    ExclusionRule(
        "name",
        r"^nvidia app\b",
        "The nvidia:install_application / *_runtime_environment entries are different"
        " products; no CPE covers the NVIDIA App control panel.",
        sample="NVIDIA App 11.0.8.299",
    ),
    ExclusionRule(
        "name",
        r"^nvidia frameview\b",
        "No CPE exists for FrameView (searched 'frameview': 0 results).",
        sample="NVIDIA FrameView SDK 1.8.12612.38276700",
    ),
    ExclusionRule(
        # The HD Audio driver's name is localized; anchor on the vendor plus the
        # component words that stay put, and keep the id suffix as the reliable half.
        "id_suffix",
        "_hdaudio.driver",
        "The HD Audio driver ships inside the graphics package but has no CPE of its"
        " own; nvidia:gpu_display_driver covers the display driver, not this component.",
        sample="ARP"
        + chr(92)
        + "Machine"
        + chr(92)
        + "X64"
        + chr(92)
        + "{B2FE1952}_HDAudio.Driver",
    ),
    ExclusionRule(
        "name",
        r"^wifi6 ",
        "An OEM adapter driver with no vendor string to search on and no CPE.",
        sample="Wifi6 802.11ax USB Adapter version 4.0.0.2",
    ),
    ExclusionRule(
        "name",
        r"^(pc health check|فحص حالة كمبيوتر)",
        "PC Health Check: no CPE exists (searched 'pc health check': 0 results).",
        sample="فحص حالة كمبيوتر بنظام Windows",
    ),
)


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


def _override_entry(product_id: str, name: str) -> CpeEntry | None:
    """A site-provided mapping, if one matches. Loaded fresh so an IT admin can add a
    mapping and see it take effect on the next scan without restarting the app."""
    from . import cpe_overrides  # local import: cpe must stay importable standalone

    nm = (name or "").strip()
    for ov in cpe_overrides.load(blocked=set(UNMAPPABLE)):
        if ov.product_id and ov.product_id == product_id:
            matched = True
        elif ov.name_pattern and nm and re.search(ov.name_pattern, nm, re.IGNORECASE):
            matched = True
        else:
            matched = False
        if matched:
            return CpeEntry(
                vendor=ov.vendor,
                product=ov.product,
                version_parts=ov.version_parts,
                # Capped at medium on purpose: it was not verified by us.
                confidence="medium",
                caveat=ov.caveat,
                source="site",
            )
    return None


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


def _exclusion_rule(product_id: str, name: str) -> ExclusionRule | None:
    """First documented exclusion matching this product, by id suffix or by name."""
    pid = (product_id or "").lower()
    nm = (name or "").strip()
    for rule in EXCLUSION_RULES:
        if rule.kind == "id_suffix":
            if pid.endswith(rule.pattern):
                return rule
        elif nm and re.search(rule.pattern, nm, re.IGNORECASE):
            return rule
    return None


def resolve(product_id: str, raw_version: str, name: str = "") -> CpeIdentity | None:
    """Map an installed product to a CPE identity, or ``None`` if we can't.

    ``None`` means one of: the product isn't in the curated map, or its version
    isn't comparable. Both are reported honestly as "not precisely matched".
    """
    entry = (
        CPE_MAP.get(product_id)
        or _fallback_entry(product_id, name)
        or _override_entry(product_id, name)
    )
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
    return (
        CPE_MAP.get(product_id)
        or _fallback_entry(product_id, name)
        or _override_entry(product_id, name)
    )


def exclusion_detail(product_id: str, name: str = "") -> str:
    """The documented reason a product cannot be matched — id-keyed or name-keyed."""
    if product_id in UNMAPPABLE:
        return UNMAPPABLE[product_id]
    rule = _exclusion_rule(product_id, name)
    return rule.reason if rule else ""


def unmatched_reason(product_id: str, raw_version: str, name: str = "") -> str:
    """Why this product produced no CPE identity — specific enough to act on.

    ``no_cpe_mapping`` used to be returned for every case, which lumped "we looked
    and NVD has nothing" together with "nobody has looked yet" and with the 57 Store
    packages NVD does not track. Those need different answers from the reader.
    """
    if (
        CPE_MAP.get(product_id)
        or _fallback_entry(product_id, name)
        or _override_entry(product_id, name)
    ):
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
    if (
        product_id in CPE_MAP
        or _fallback_entry(product_id, name) is not None
        or _override_entry(product_id, name) is not None
    ):
        return "mapped"
    if product_id in UNMAPPABLE:
        return "documented_exclusion"
    # Store packages are classified BEFORE the name rules on purpose: being an MSIX
    # identity is a structural fact about the version, and a prefix rule written for a
    # desktop product would otherwise claim a same-named Store app with the wrong
    # reason (measured: "Microsoft 365 Copilot" was captured by the Office rule).
    if product_id.startswith("MSIX" + "\\") or product_id.startswith("MSIX/"):
        return "store_package"
    if _exclusion_rule(product_id, name) is not None:
        return "documented_exclusion"
    return "not_investigated"


def coverage(products: list[tuple[str, str]] | list[str]) -> dict:
    """How much of an inventory the curated map can precisely match.

    Surfaced to the UI/report so the gap is visible instead of implied: a report
    that silently covers 30% of an estate is worse than one that says so. The raw
    ``percent`` stays the headline — the breakdown explains it, it does not replace
    it, and ``addressable_percent`` is reported next to it, never instead of it.

    Accepts ``(product_id, name)`` pairs, or ``(product_id, name, version)`` triples; a
    bare list of ids still works, but then the name-based rules cannot apply and coverage
    reads lower than reality.

    **Pass the version when you have it.** Without it "mapped" means only that the
    product is in the curated map — and a product can be in the map and still be
    unmatchable, because its installed version is not comparable. Measured on a real
    inventory: "PowerToys (Preview)" at version "> 0.75.1" was counted as mapped while
    ``resolve`` refused it, so the pack printed 78.6% where the honest figure was 71.4%.
    A coverage number that counts products it could not actually check is the one number
    in this document that must not be optimistic.
    """
    rows = []
    for p in products:
        if isinstance(p, str):
            rows.append((p, "", None))
        elif len(p) >= 3:
            rows.append((p[0], p[1] or "", p[2]))
        else:
            rows.append((p[0], p[1] or "", None))
    total = len(rows)
    buckets = {
        "mapped": 0,
        "documented_exclusion": 0,
        "store_package": 0,
        "not_investigated": 0,
        "version_not_comparable": 0,
    }
    for pid, nm, version in rows:
        bucket = classify_unmapped(pid, nm)
        if bucket == "mapped" and version is not None and resolve(pid, version, nm) is None:
            bucket = "version_not_comparable"
        buckets[bucket] += 1
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
