"""
Software-update integration via winget.

We shell out to ``winget upgrade`` to list packages with a newer version
available, and to ``winget upgrade <id>`` to install one. Output is parsed
from the column-based table because winget's JSON output is not stable
across versions.

Public API:
  - list_software_updates() -> (list[SoftwarePackageInfo], degraded: bool)
  - install_software_update(package_id) -> dict (exit code, output)
  - install_many(package_ids) -> dict (aggregated)
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from .adaptive_timeout import StallWatchdog
from .update_progress import update_progress


@dataclass
class SoftwarePackageInfo:
    """One winget package with an upgrade available."""

    package_id: str  # e.g. "Mozilla.Firefox"
    name: str  # e.g. "Mozilla Firefox"
    current_version: str
    available_version: str
    source: str  # "winget" / "msstore"
    size_mb: float = 0.0  # winget rarely reports size; fill 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InstalledSoftwareInfo:
    """One product that is actually INSTALLED (from ``winget list``).

    Distinct from ``SoftwarePackageInfo``, which only ever describes a package
    that HAS an upgrade waiting. Inventory answers "what is on this machine",
    which is what precise (product+version) CVE matching and any asset report
    need. ``publisher`` is empty here: ``winget list`` does not print it — a
    registry/MSI source can fill it later without changing this shape.
    """

    product_id: str  # winget Id, e.g. "Mozilla.Firefox"
    name: str
    version: str
    source: str = "winget"
    publisher: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SoftwareUpdateError(RuntimeError):
    """Raised when winget fails (not installed, no network, etc.)."""


# ===================================================================
# Internal helpers
# ===================================================================
def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise SoftwareUpdateError("winget is only available on Windows")


# winget / MSI exit codes that are NOT install failures. A plain ``rc == 0``
# check wrongly marks these as failed, so the package is persisted
# is_installed=False and reappears as "pending" on every later check — the root
# cause of a persistent "the update keeps failing" report.
#   3010 (0x00000BC2) ERROR_SUCCESS_REBOOT_REQUIRED  — installed; reboot to finish
#   1641 (0x00000669) ERROR_SUCCESS_REBOOT_INITIATED — installed; reboot started
#   0x8A15002B        APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE — nothing to do
# An HRESULT with the high bit set arrives as a signed int32 (0x8A15002B ->
# -1978335189), so normalise to the unsigned DWORD before comparing.
_REBOOT_REQUIRED_CODES = frozenset({3010, 1641})
_WINGET_NOOP_CODES = frozenset({0x8A15002B})


def _as_dword(rc: int) -> int:
    """Normalise a process exit code to an unsigned 32-bit value."""
    return rc & 0xFFFFFFFF


def _classify_winget_rc(rc: int) -> tuple[bool, bool]:
    """Return ``(succeeded, reboot_required)`` for a winget exit code.

    Only a genuine failure code yields succeeded=False. 0 is success; the
    reboot-required codes and "update not applicable" are benign non-failures
    that a raw ``rc == 0`` would misread as failures.
    """
    code = _as_dword(rc)
    if code == 0:
        return True, False
    if code in _REBOOT_REQUIRED_CODES:
        return True, True
    if code in _WINGET_NOOP_CODES:
        return True, False
    return False, False


async def _run(
    *args: str,
    idle_timeout: float = 180.0,
    hard_ceiling: float = 1800.0,
) -> tuple[int, str, str]:
    """Run a command, bounded by a STALL WATCHDOG on its output, not a fixed clock.

    winget emits download/percent progress as it works, so we keep it alive while
    output keeps arriving and abort only after ``idle_timeout`` seconds of total
    silence (a genuinely stuck process) or ``hard_ceiling`` seconds overall. A
    single fixed timeout can't bound a multi-minute install correctly — it either
    cuts a slow-but-live install short or waits far too long on a wedged one.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,  # windowed builds have no valid stdin handle
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    watchdog = StallWatchdog(stall_window=idle_timeout, hard_ceiling=hard_ceiling)
    out: list[bytes] = []
    err: list[bytes] = []

    async def _pump(stream: asyncio.StreamReader, sink: list[bytes]) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            sink.append(chunk)
            watchdog.progress(len(chunk))  # any output resets the silence clock

    pumps = [
        asyncio.create_task(_pump(proc.stdout, out)),
        asyncio.create_task(_pump(proc.stderr, err)),
    ]
    try:
        while True:
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                break  # process exited on its own
            except TimeoutError:
                if watchdog.stalled():
                    await _terminate_tree(proc)
                    # Bound the drain: a spawned installer may inherit the pipe
                    # and hold it open, which would otherwise block forever and
                    # wedge update_progress.is_running=True (409 on every later op).
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=10.0)
                    except TimeoutError:
                        pass
                    reason = (
                        f"no output for {int(idle_timeout)}s"
                        if watchdog.idle_seconds() >= idle_timeout
                        else f"exceeded {int(hard_ceiling)}s"
                    )
                    raise SoftwareUpdateError(
                        f"Command stalled ({reason}): {' '.join(args)}"
                    ) from None
        # Exited on its own: let the pumps drain buffered output, but bound it in
        # case a child inherited the pipe and holds it open past process exit.
        try:
            await asyncio.wait_for(asyncio.gather(*pumps), timeout=10.0)
        except TimeoutError:
            pass
    finally:
        for pump in pumps:
            if not pump.done():
                pump.cancel()
    return (
        proc.returncode or 0,
        b"".join(out).decode("utf-8", errors="replace"),
        b"".join(err).decode("utf-8", errors="replace"),
    )


async def _terminate_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process AND its children. proc.kill() only signals winget.exe, so
    the installer (MSI/EXE) winget spawned would keep running detached and finish
    the install while HomeUpdater reports failure. taskkill /T kills the tree."""
    if sys.platform == "win32" and proc.pid:
        try:
            tk = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(tk.wait(), timeout=10.0)
        except Exception:  # noqa: BLE001 — best-effort; fall through to proc.kill()
            pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


_KNOWN_SOURCES = {"winget", "msstore"}


def _is_separator_row(line: str) -> bool:
    """A winget table separator is a run of dashes, independent of UI language."""
    s = line.strip()
    return len(s) >= 10 and set(s) <= {"-", "─"}


def _parse_winget_row(line: str) -> SoftwarePackageInfo | None:
    """Parse a single data row language- and alignment-independently.

    Columns are separated by runs of 2+ spaces, while a package NAME uses only
    single spaces internally. Splitting on 2+ spaces therefore recovers the
    fields even when the header is localized (Arabic) or the data columns don't
    line up under the header. We anchor from the RIGHT — Id, Version, Available
    and Source are all space-free tokens — so multi-word names are handled.
    """
    fields = re.split(r"\s{2,}", line.strip())
    if len(fields) < 4:
        return None

    source = "winget"
    if fields[-1].lower() in _KNOWN_SOURCES:
        source = fields[-1].lower()
        fields = fields[:-1]
    if len(fields) < 3:
        return None

    pkg_id, current, available = fields[-3], fields[-2], fields[-1]
    name = " ".join(fields[:-3]).strip()

    # Structural validation (no language-specific words): a winget Id is a
    # single space-free token and the current column is a version (has a digit).
    # This drops localized headers and footers without matching their wording.
    if not pkg_id or " " in pkg_id or not re.search(r"\d", current):
        return None
    if not available or available.lower().startswith("<unknown"):
        return None

    return SoftwarePackageInfo(
        package_id=pkg_id,
        name=name,
        current_version=current,
        available_version=available,
        source=source,
    )


def _parse_winget_table(text: str) -> list[SoftwarePackageInfo]:
    """Parse ``winget upgrade`` output independently of the console UI language.

    winget localizes the column headers (Name/Id/Version/Available/Source ->
    الاسم/المعرف/الإصدار/متوفر/المصدر on Arabic Windows) but keeps a
    locale-independent dashes separator row. We locate that separator and parse
    each following row until a blank line (which precedes the footer / second
    "unknown version" section). The previous English-keyword parser returned
    zero rows on Arabic Windows, which then made the caller mark every package
    as "installed". If no separator is present we scan all lines and let the
    per-row structural validation reject non-data lines.
    """
    lines = text.splitlines()
    sep_idx = next((i for i, ln in enumerate(lines) if _is_separator_row(ln)), None)
    data_lines = lines[sep_idx + 1 :] if sep_idx is not None else lines

    packages: list[SoftwarePackageInfo] = []
    for line in data_lines:
        if not line.strip():
            if sep_idx is not None:
                break  # blank line ends the main table
            continue
        pkg = _parse_winget_row(line)
        if pkg is not None:
            packages.append(pkg)
    return packages


def _looks_like_winget_id(token: str) -> bool:
    """Is this token shaped like a winget Id (``Publisher.Product``, ``MSIX\\…``)?

    Requires a dot or backslash AND at least one letter, so a bare version such
    as ``14.51.36247`` is not mistaken for an Id when repairing a collided row.
    """
    if not token or not re.search(r"[A-Za-z]", token):
        return False
    return "." in token or "\\" in token


def _parse_winget_list_row(line: str) -> InstalledSoftwareInfo | None:
    """Parse one ``winget list`` row — language- and column-count-independent.

    ``winget list`` differs from ``winget upgrade`` in the way that matters: the
    Available column is usually EMPTY, so a row carries 3 fields (Name, Id,
    Version) or 4 (+Source), and only occasionally 5 (+Available). The upgrade
    parser requires an Available value and would drop nearly every installed
    product, which is why this needs its own row rule.

    Same locale-safe technique: split on runs of 2+ spaces and anchor from the
    right, since Id/Version/Source are space-free tokens while a product name
    uses single spaces internally.
    """
    fields = re.split(r"\s{2,}", line.strip())
    if len(fields) < 2:
        return None

    source = "winget"
    if fields[-1].lower() in _KNOWN_SOURCES:
        source = fields[-1].lower()
        fields = fields[:-1]
    if len(fields) < 2:
        return None

    # With an Available column present the trailing field is that, not Version.
    # Both are version-shaped, so decide on COUNT: >=4 remaining fields means
    # Name… Id Version Available.
    if len(fields) >= 4:
        product_id, version = fields[-3], fields[-2]
        name = " ".join(fields[:-3]).strip()
    else:
        product_id, version = fields[-2], fields[-1]
        name = " ".join(fields[:-2]).strip()

    # REPAIR a collided row. When a long Name overflows its column only ONE space
    # separates it from the Id, so both land in a single field, e.g.
    #   "Microsoft Visual C++ … (x64) - 14.51.36247 Microsoft.VCRedist.2015+.x64"
    # Recover by taking the trailing Id-shaped token. Verified against real
    # `winget list` output, where this silently dropped VCRedist — exactly the
    # kind of product that matters for vulnerability matching.
    if " " in product_id and "\\" not in product_id:
        tokens = product_id.split()
        if len(tokens) >= 2 and _looks_like_winget_id(tokens[-1]):
            name = f"{name} {' '.join(tokens[:-1])}".strip()
            product_id = tokens[-1]

    # Structural validation only — no language-specific words, so localized
    # headers/footers are rejected without matching their wording. A version must
    # contain a digit, which is what drops the Arabic header row (its "version"
    # cell is a word). Ids are usually space-free, but path-style ones legitimately
    # contain spaces (e.g. "ARP\\Machine\\X64\\O365HomePremRetail - ar-sa"), so
    # spaces are tolerated only when the Id is backslash-qualified.
    if not product_id or (" " in product_id and "\\" not in product_id):
        return None
    if not version or not re.search(r"\d", version):
        return None

    return InstalledSoftwareInfo(
        product_id=product_id, name=name or product_id, version=version, source=source
    )


def parse_winget_list(text: str) -> list[InstalledSoftwareInfo]:
    """Parse ``winget list`` output into an installed-software inventory.

    Locates the locale-independent dashes separator and reads the rows after it,
    de-duplicating by product id (winget can list the same id twice, e.g. an
    x86 and an x64 entry) — keeping the FIRST occurrence, which matches the
    one-row-per-(device, product) shape of ``installed_software``.
    """
    lines = text.splitlines()
    sep_idx = next((i for i, ln in enumerate(lines) if _is_separator_row(ln)), None)
    data_lines = lines[sep_idx + 1 :] if sep_idx is not None else lines

    out: list[InstalledSoftwareInfo] = []
    seen: set[str] = set()
    for line in data_lines:
        if not line.strip():
            if sep_idx is not None:
                break  # blank line ends the table (footer follows)
            continue
        item = _parse_winget_list_row(line)
        if item is None or item.product_id in seen:
            continue
        seen.add(item.product_id)
        out.append(item)
    return out


# ===================================================================
# Public async API
# ===================================================================
async def list_installed_software() -> tuple[list[InstalledSoftwareInfo], bool]:
    """Inventory what is installed on THIS machine via ``winget list``.

    Returns ``(items, degraded)``. ``degraded`` is True when winget exited
    non-zero, so the caller must not treat a short list as authoritative and
    prune rows that are merely missing from partial output.
    """
    _ensure_windows()
    rc, stdout, stderr = await _run(
        "winget",
        "list",
        "--accept-source-agreements",
        "--disable-interactivity",
        idle_timeout=60.0,
        hard_ceiling=240.0,  # a full inventory is longer than an upgrade listing
    )
    if rc != 0 and not stdout.strip():
        raise SoftwareUpdateError(f"winget exited with code {rc}: {stderr.strip() or 'no output'}")
    items = parse_winget_list(stdout)
    logger.info(f"inventory: {len(items)} installed product(s) (winget rc={rc})")
    return items, rc != 0


async def list_software_updates() -> tuple[list[SoftwarePackageInfo], bool]:
    """List installed apps that have an upgrade available.

    Returns ``(packages, degraded)``. ``degraded`` is True when winget exited
    non-zero (partial output / a parser miss possible) so the caller must NOT
    infer that packages absent from this list were upgraded externally — doing so
    would make real pending upgrades silently vanish as "done".
    """
    _ensure_windows()
    update_progress.begin("check-software")
    update_progress.set_phase("checking", "Asking winget for available app upgrades")

    try:
        rc, stdout, stderr = await _run(
            "winget",
            "upgrade",
            "--include-unknown",
            "--accept-source-agreements",
            idle_timeout=60.0,  # a listing should never sit silent this long
            hard_ceiling=180.0,
        )
        if rc != 0 and not stdout.strip():
            raise SoftwareUpdateError(
                f"winget exited with code {rc}: {stderr.strip() or 'no output'}"
            )
        degraded = rc != 0
        packages = _parse_winget_table(stdout)
        update_progress.update_progress(
            completed=len(packages),
            total=len(packages),
            message=f"Found {len(packages)} app(s) with updates",
        )
    except SoftwareUpdateError as exc:
        update_progress.fail(str(exc))
        raise
    except Exception as exc:
        logger.exception("winget list failed")
        update_progress.fail(str(exc))
        raise SoftwareUpdateError(str(exc)) from exc

    update_progress.finish(f"Check complete - {len(packages)} update(s) available")
    return packages, degraded


async def install_software_update(package_id: str) -> dict[str, Any]:
    """Upgrade a single winget package."""
    _ensure_windows()
    update_progress.set_phase("installing", f"Installing {package_id}")
    rc, stdout, stderr = await _run(
        "winget",
        "upgrade",
        package_id,
        "--silent",
        "--accept-source-agreements",
        "--accept-package-agreements",
        # Kill only on 10 min of TOTAL silence (a stuck installer) or 60 min
        # overall — winget goes quiet during a large MSI's apply phase, so the
        # window is generous to avoid cutting a big-but-live install short.
        idle_timeout=600.0,
        hard_ceiling=3600.0,
    )
    succeeded, reboot_required = _classify_winget_rc(rc)
    return {
        "package_id": package_id,
        "exit_code": rc,
        "succeeded": succeeded,
        "reboot_required": reboot_required,
        "stdout_tail": stdout[-500:] if stdout else "",
        "stderr_tail": stderr[-500:] if stderr else "",
    }


async def install_many(package_ids: list[str]) -> dict[str, Any]:
    """Install several packages sequentially. Returns aggregated results."""
    update_progress.begin("install-software", total=len(package_ids))
    results = []
    succeeded = 0
    reboot_required = False
    for i, pkg_id in enumerate(package_ids, 1):
        update_progress.update_progress(
            completed=i - 1,
            total=len(package_ids),
            message=f"Installing {pkg_id} ({i}/{len(package_ids)})",
        )
        try:
            r = await install_software_update(pkg_id)
        except Exception as exc:
            r = {
                "package_id": pkg_id,
                "exit_code": -1,
                "succeeded": False,
                "reboot_required": False,
                "stderr_tail": str(exc),
            }
        results.append(r)
        if r.get("succeeded"):
            succeeded += 1
        if r.get("reboot_required"):
            reboot_required = True

    update_progress.finish(f"Installed {succeeded}/{len(package_ids)}")
    return {
        "installed": succeeded,
        "total": len(package_ids),
        "reboot_required": reboot_required,
        "results": results,
    }
