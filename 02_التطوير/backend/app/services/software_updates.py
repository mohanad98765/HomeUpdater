"""
Software-update integration via winget.

We shell out to ``winget upgrade`` to list packages with a newer version
available, and to ``winget upgrade <id>`` to install one. Output is parsed
from the column-based table because winget's JSON output is not stable
across versions.

Public API:
  - list_software_updates() -> list[SoftwarePackageInfo]
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


async def _run(*args: str, timeout: float = 600.0) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise SoftwareUpdateError(f"Command timed out: {' '.join(args)}") from None
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
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
async def list_software_updates() -> list[SoftwarePackageInfo]:
    """List installed apps that have an upgrade available."""
    _ensure_windows()
    update_progress.begin("check-software")
    update_progress.set_phase("checking", "Asking winget for available app upgrades")

    try:
        rc, stdout, stderr = await _run(
            "winget",
            "upgrade",
            "--include-unknown",
            "--accept-source-agreements",
            timeout=120.0,
        )
        if rc != 0 and not stdout.strip():
            raise SoftwareUpdateError(
                f"winget exited with code {rc}: {stderr.strip() or 'no output'}"
            )
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
    return packages


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
        timeout=1200.0,  # 20 minutes per package — some are big
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
