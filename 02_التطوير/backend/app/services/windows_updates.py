"""
Windows Update integration via the Windows Update Agent (WUA) COM API.

Uses pywin32's ``win32com.client`` to talk to ``Microsoft.Update.Session``,
which is the same engine the Settings > Windows Update UI uses. Requires
Administrator privileges (already enforced by run.bat auto-elevate).

Public API:
  - check_for_updates() -> list of UpdateInfo dicts
  - install_updates(update_ids) -> install one or more (by their UpdateID)

Both run nmap-style: blocking COM calls happen in a thread executor so the
FastAPI event loop is never blocked. Progress is reported via update_progress
singleton so the UI can poll a live activity feed.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from .adaptive_timeout import DurationCeiling
from .update_progress import update_progress

# Adaptive wall-clock ceilings for the opaque WUA COM calls (no intra-call
# progress signal exists, so a stall-watchdog can't help — only a bound can).
# They start generous and tighten toward each machine's real search/install time.
_CHECK_CEILING = DurationCeiling(floor=120.0, ceiling=900.0, safety=3.0)  # search
_INSTALL_CEILING = DurationCeiling(floor=600.0, ceiling=3600.0, safety=3.0)  # download+install

# Severity values returned by Microsoft Update — keep as strings for the UI.
SEVERITY_LEVELS = ("Critical", "Important", "Moderate", "Low", "Unspecified")


@dataclass
class UpdateInfo:
    """One pending Windows update."""

    update_id: str  # WUA UpdateIdentity.UpdateID (used to re-find it for install)
    title: str
    description: str
    kb_articles: list[str]  # e.g. ["KB5034441"]
    severity: str  # "Critical" / "Important" / etc. or ""
    size_mb: float  # MaxDownloadSize in MB
    is_downloaded: bool
    requires_reboot: bool
    categories: list[str]  # e.g. ["Security Updates"]
    release_date: str | None = None  # ISO date if available

    def to_dict(self) -> dict:
        return asdict(self)


class WindowsUpdateError(RuntimeError):
    """Raised for any WUA-related failure (COM init, search, install)."""


# ===================================================================
# Internal helpers
# ===================================================================
def _ensure_windows() -> None:
    """COM-via-pywin32 is Windows-only."""
    if sys.platform != "win32":
        raise WindowsUpdateError("Windows Update API is only available on Windows")


def _make_session():
    """Create a Windows Update Session.

    COM MUST already be initialized by the caller (CoInitialize). Keeping
    CoInitialize/CoUninitialize in the caller's try/finally guarantees they
    stay balanced even if this Dispatch raises — otherwise a failed Dispatch
    would leak a CoInitialize that is never released.
    """
    import win32com.client  # type: ignore[import-not-found]

    session = win32com.client.Dispatch("Microsoft.Update.Session")
    session.ClientApplicationID = "HomeUpdater"
    return session


# ===================================================================
# Check (blocking)
# ===================================================================
def _check_blocking(kind: str = "Software") -> list[UpdateInfo]:
    """
    Synchronous: search for pending updates of the given kind.
    kind = "Software" (Windows updates) or "Driver" (driver updates).
    """
    _ensure_windows()
    import pythoncom  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    try:
        session = _make_session()
        searcher = session.CreateUpdateSearcher()
        update_progress.set_phase(
            "checking",
            f"Querying Windows Update for {kind.lower()} updates (1-3 minutes)",
        )
        result = searcher.Search(f"IsInstalled=0 and IsHidden=0 and Type='{kind}'")

        updates: list[UpdateInfo] = []
        total = result.Updates.Count
        update_progress.set_phase("checking", f"Found {total} pending update(s); reading details")

        for i in range(total):
            u = result.Updates.Item(i)
            try:
                size_bytes = int(u.MaxDownloadSize)
            except Exception:
                size_bytes = 0
            try:
                kb = list(u.KBArticleIDs)
            except Exception:
                kb = []
            try:
                cats = [c.Name for c in u.Categories]
            except Exception:
                cats = []
            try:
                release_date = u.LastDeploymentChangeTime.strftime("%Y-%m-%d")
            except Exception:
                release_date = None

            info = UpdateInfo(
                update_id=str(u.Identity.UpdateID),
                title=str(u.Title or ""),
                description=str(u.Description or ""),
                kb_articles=[f"KB{n}" for n in kb],
                severity=str(u.MsrcSeverity or "Unspecified"),
                size_mb=round(size_bytes / (1024 * 1024), 2),
                is_downloaded=bool(u.IsDownloaded),
                requires_reboot=bool(getattr(u, "RebootRequired", False)),
                categories=cats,
                release_date=release_date,
            )
            updates.append(info)
            update_progress.update_progress(
                completed=i + 1,
                total=total,
                message=f"Read details for: {info.title[:80]}",
            )

        return updates
    except Exception as exc:
        logger.exception("Windows Update search failed")
        raise WindowsUpdateError(f"Search failed: {exc}") from exc
    finally:
        pythoncom.CoUninitialize()


# ===================================================================
# Install (blocking)
# ===================================================================
def _install_blocking(update_ids: list[str]) -> dict[str, Any]:
    """Synchronous: download + install the chosen updates. Run in executor."""
    _ensure_windows()
    if not update_ids:
        # "total" must be present — install_updates() formats result['total'].
        return {"installed": 0, "total": 0, "reboot_required": False, "results": []}

    import pythoncom  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    try:
        session = _make_session()
        # 1) Re-find the chosen updates by ID
        # Search both Software and Driver so install works for either kind
        update_progress.set_phase("downloading", "Locating selected updates")
        searcher = session.CreateUpdateSearcher()
        result = searcher.Search("IsInstalled=0 and IsHidden=0")

        import win32com.client  # type: ignore[import-not-found]

        wanted = win32com.client.Dispatch("Microsoft.Update.UpdateColl")
        for i in range(result.Updates.Count):
            u = result.Updates.Item(i)
            if str(u.Identity.UpdateID) in update_ids:
                # Some updates require EULA acceptance
                try:
                    if hasattr(u, "EulaAccepted") and not u.EulaAccepted:
                        u.AcceptEula()
                except Exception:
                    pass
                wanted.Add(u)

        if wanted.Count == 0:
            raise WindowsUpdateError("None of the requested updates were found")

        # 2) Download
        update_progress.set_phase("downloading", f"Downloading {wanted.Count} update(s)")
        downloader = session.CreateUpdateDownloader()
        downloader.Updates = wanted
        download_result = downloader.Download()
        if download_result.ResultCode not in (2, 3):  # 2=Succeeded, 3=SucceededWithErrors
            raise WindowsUpdateError(f"Download failed (ResultCode={download_result.ResultCode})")

        # 3) Install only the items that downloaded successfully
        to_install = win32com.client.Dispatch("Microsoft.Update.UpdateColl")
        for i in range(wanted.Count):
            if wanted.Item(i).IsDownloaded:
                to_install.Add(wanted.Item(i))

        if to_install.Count == 0:
            raise WindowsUpdateError("No updates were downloaded successfully")

        update_progress.set_phase("installing", f"Installing {to_install.Count} update(s)")
        installer = session.CreateUpdateInstaller()
        installer.Updates = to_install
        install_result = installer.Install()

        # 4) Build per-update result list
        results = []
        for i in range(to_install.Count):
            u = to_install.Item(i)
            r = install_result.GetUpdateResult(i)
            results.append(
                {
                    "update_id": str(u.Identity.UpdateID),
                    "title": str(u.Title or ""),
                    "result_code": int(r.ResultCode),  # 2 = Succeeded
                    "hresult": int(r.HResult),
                    "succeeded": int(r.ResultCode) == 2,
                }
            )

        succeeded = sum(1 for x in results if x["succeeded"])
        reboot = bool(install_result.RebootRequired)
        if reboot:
            update_progress.reboot_required()

        update_progress.update_progress(
            completed=succeeded,
            total=to_install.Count,
            message=f"Installed {succeeded}/{to_install.Count}"
            + (" (reboot required)" if reboot else ""),
        )

        return {
            "installed": succeeded,
            "total": to_install.Count,
            "reboot_required": reboot,
            "results": results,
        }
    except WindowsUpdateError:
        raise
    except Exception as exc:
        logger.exception("Windows Update install failed")
        raise WindowsUpdateError(f"Install failed: {exc}") from exc
    finally:
        pythoncom.CoUninitialize()


# ===================================================================
# Public async API
# ===================================================================
async def _run_bounded(fn, *args, ceiling: DurationCeiling, op: str):
    """Run a blocking WUA COM call in a thread, bounded by an adaptive ceiling.

    WUA's Search/Download/Install are opaque COM calls; if the Windows Update
    service wedges they block forever. Previously the ``await`` then hung
    indefinitely AND left ``update_progress.is_running`` set, so every later
    update request returned 409 for the life of the process. We bound it with
    ``DurationCeiling`` (EWMA of prior successful runs × safety, clamped) and use
    ``asyncio.wait`` — NOT ``wait_for`` — so the timeout never blocks on the
    uncancellable COM thread. On overrun we raise; the caller clears progress.
    The orphaned thread finishes on its own later (COM has no cancellation) but
    can no longer wedge the app.
    """
    loop = asyncio.get_event_loop()
    deadline = ceiling.timeout()
    started = time.monotonic()
    fut = loop.run_in_executor(None, fn, *args)
    done, _pending = await asyncio.wait({fut}, timeout=deadline)
    if not done:
        raise WindowsUpdateError(
            f"{op} exceeded {int(deadline)}s and was abandoned — the Windows "
            f"Update service may be stuck. Reboot and retry if this recurs."
        )
    result = fut.result()  # re-raises the thread's own exception if it failed
    ceiling.observe(time.monotonic() - started)
    return result


async def check_for_updates(kind: str = "Software") -> list[UpdateInfo]:
    """Search Windows Update for pending updates of the given kind."""
    update_progress.begin(f"check-{kind.lower()}")
    try:
        result = await _run_bounded(
            _check_blocking,
            kind,
            ceiling=_CHECK_CEILING,
            op=f"Windows Update {kind.lower()} search",
        )
    except WindowsUpdateError as exc:
        update_progress.fail(str(exc))
        raise
    except Exception as exc:
        update_progress.fail(str(exc))
        raise WindowsUpdateError(str(exc)) from exc
    update_progress.finish(f"Check complete - {len(result)} {kind.lower()} update(s) pending")
    return result


async def install_updates(update_ids: list[str]) -> dict[str, Any]:
    """Download + install the given updates (runs in executor)."""
    update_progress.begin("install", total=len(update_ids))
    try:
        result = await _run_bounded(
            _install_blocking, update_ids, ceiling=_INSTALL_CEILING, op="Windows Update install"
        )
    except WindowsUpdateError as exc:
        update_progress.fail(str(exc))
        raise
    except Exception as exc:
        update_progress.fail(str(exc))
        raise WindowsUpdateError(str(exc)) from exc

    msg = f"Installed {result['installed']}/{result['total']}"
    if result.get("reboot_required"):
        msg += " - reboot required"
    update_progress.finish(msg)
    return result
