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


class SoftwareUpdateError(RuntimeError):
    """Raised when winget fails (not installed, no network, etc.)."""


# ===================================================================
# Internal helpers
# ===================================================================
def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise SoftwareUpdateError("winget is only available on Windows")


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
                    proc.kill()
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


# ===================================================================
# Public async API
# ===================================================================
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
        # Kill only on 5 min of TOTAL silence (a stuck installer) or 30 min
        # overall — never mid-progress, so a big-but-live install isn't cut short.
        idle_timeout=300.0,
        hard_ceiling=1800.0,
    )
    return {
        "package_id": package_id,
        "exit_code": rc,
        "succeeded": rc == 0,
        "stdout_tail": stdout[-500:] if stdout else "",
        "stderr_tail": stderr[-500:] if stderr else "",
    }


async def install_many(package_ids: list[str]) -> dict[str, Any]:
    """Install several packages sequentially. Returns aggregated results."""
    update_progress.begin("install-software", total=len(package_ids))
    results = []
    succeeded = 0
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
                "stderr_tail": str(exc),
            }
        results.append(r)
        if r.get("succeeded"):
            succeeded += 1

    update_progress.finish(f"Installed {succeeded}/{len(package_ids)}")
    return {
        "installed": succeeded,
        "total": len(package_ids),
        "results": results,
    }
