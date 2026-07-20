"""
Android device integration via the bundled official ``adb`` binary.

Earlier versions used the pure-Python ``adb-shell`` library, but it cannot
perform the **Android 11+ Wireless-debugging** handshake (ADB-over-TLS +
pairing): the phone replies ``STLS`` and the connection fails. We now ship
Google's ``adb.exe`` (see ``vendor/platform-tools``) and drive it as a
subprocess, which supports pairing, TLS wireless connect, and the legacy
``adb connect IP:5555`` path all at once.

Public API (all async):
  - pair(host, port, code)          -> pair with Wireless debugging (one-time)
  - probe(host, port)               -> DeviceInfo (connect + read properties)
  - list_apps(host, port)           -> installed 3rd-party apps
  - open_play_store(host, port, pkg)-> ask Android to open the Play page

adb manages its own RSA key (``%USERPROFILE%\\.android``) and the phone
prompts "Allow debugging?" the first time a new host connects.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

# list_apps() spawns one dumpsys per app to read its version; bound that work.
_APP_VERSION_CAP = 120  # enrich at most this many apps
_APP_ENRICH_BUDGET_S = 25.0  # ...and stop enriching after this wall-clock budget
# How long to poll `adb mdns services` for a freshly-advertised connect port.
_MDNS_DISCOVER_BUDGET_S = 6.0

# A valid Android package name is dot-separated alphanumerics/underscores only.
# Enforced before it is ever passed to `am start`, to block injection through
# the /apps/{package_name}/open path parameter.
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")
# A host we are willing to hand to adb. IPv4 or a simple hostname — crucially it
# must NOT start with '-' (which adb would parse as a flag) and contains no shell
# metacharacters. Ports are ints (validated by the router), so are always safe.
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")
# Wireless-debugging pairing codes are exactly six digits.
_CODE_RE = re.compile(r"^\d{6}$")
# `adb mdns services` row for the connect endpoint:
#   adb-XXXX-YYYY\t_adb-tls-connect._tcp\t192.168.3.30:34677
_MDNS_CONNECT_RE = re.compile(r"_adb-tls-connect\._tcp\s+([0-9.]+):(\d+)")

# Avoid flashing a console window from the windowed (WebView2) app.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# ==================================================================
# Errors + result types
# ==================================================================
class AndroidError(RuntimeError):
    """Raised when an ADB operation fails."""


@dataclass
class DeviceInfo:
    """Snapshot of Android device properties read via getprop."""

    host: str
    port: int
    serial: str
    manufacturer: str
    model: str
    brand: str
    android_version: str
    sdk_version: str
    security_patch: str

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "serial": self.serial,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "brand": self.brand,
            "android_version": self.android_version,
            "sdk_version": self.sdk_version,
            "security_patch": self.security_patch,
            "display_name": f"{self.manufacturer} {self.model}".strip() or self.serial,
        }


@dataclass
class AppInfo:
    """One installed app on an Android device."""

    package_name: str
    version_name: str = ""
    version_code: str = ""
    apk_path: str = ""
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "package_name": self.package_name,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "apk_path": self.apk_path,
            "label": self.label or self.package_name,
        }


# ==================================================================
# Locating + running the bundled adb
# ==================================================================
def _adb_exe() -> str | None:
    """Locate the adb binary: bundled (frozen) -> vendored (source) -> PATH."""
    names = ["adb.exe"] if sys.platform == "win32" else ["adb"]
    dirs: list[Path] = []
    base = getattr(sys, "_MEIPASS", None)
    if base:  # PyInstaller onedir: platform-tools bundled next to the app
        dirs.append(Path(base) / "platform-tools")
    # source tree: app/services/android.py -> backend/vendor/platform-tools
    dirs.append(Path(__file__).resolve().parent.parent.parent / "vendor" / "platform-tools")
    for d in dirs:
        for n in names:
            p = d / n
            if p.is_file():
                return str(p)
    return shutil.which("adb")


def _have_adb() -> bool:
    return _adb_exe() is not None


def _run_adb_blocking(
    args: list[str], timeout: float = 30.0, input_text: str | None = None
) -> tuple[int, str, str]:
    """Run adb with the given args. Returns (returncode, stdout, stderr)."""
    exe = _adb_exe()
    if not exe:
        raise AndroidError("لم يُعثر على أداة adb المضمّنة — أعد تثبيت البرنامج.")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise AndroidError(f"انتهت مهلة adb ({' '.join(args[:2])}).") from exc
    except OSError as exc:
        raise AndroidError(f"تعذّر تشغيل adb: {exc}") from exc
    return proc.returncode, proc.stdout or "", proc.stderr or ""


async def _in_executor(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# ==================================================================
# Pure parsing / validation helpers (unit-tested)
# ==================================================================
def _validate_host(host: str) -> None:
    if not host or not _HOST_RE.match(host):
        raise AndroidError(f"عنوان غير صالح: {host!r}")


_PROP_LINE = re.compile(r"^\[([^\]]+)\]:\s*\[(.*)\]$")


def _parse_getprop(output: str) -> dict[str, str]:
    """Parse ``adb shell getprop`` output ("[key]: [value]" per line)."""
    props: dict[str, str] = {}
    for line in output.splitlines():
        m = _PROP_LINE.match(line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def _parse_mdns_connect(output: str, host: str) -> int | None:
    """Find the Wireless-debugging connect port for ``host`` in the output of
    ``adb mdns services``. Returns None if this host isn't advertising."""
    for m in _MDNS_CONNECT_RE.finditer(output):
        if m.group(1) == host:
            return int(m.group(2))
    return None


def _clean_adb_msg(out: str, err: str) -> str:
    """Build a user-facing message, dropping adb's daemon-startup noise
    ("* daemon not running; starting now …") that pollutes the first call."""
    lines = [
        ln.strip()
        for ln in f"{out}\n{err}".splitlines()
        if ln.strip() and not ln.lstrip().startswith("*")
    ]
    return " ".join(lines).strip()


def _check_pair_result(rc: int, out: str, err: str) -> None:
    if "successfully paired" in f"{out}\n{err}".lower():
        return
    msg = _clean_adb_msg(out, err) or f"adb pair exited {rc}"
    raise AndroidError(f"فشل الإقران: {msg[:200]}")


def _check_connect_result(rc: int, out: str, err: str) -> None:
    text = f"{out} {err}".lower()
    if "connected to" in text or "already connected" in text:
        return
    msg = _clean_adb_msg(out, err) or f"adb connect exited {rc}"
    raise AndroidError(f"تعذّر الاتصال: {msg[:200]}")


def _parse_pkg_versions(dump: str) -> tuple[str, str]:
    """Extract (versionName, versionCode) from ``dumpsys package`` output.

    Guards the versionCode split: an empty value would otherwise IndexError.
    """
    name, code = "", ""
    for raw in dump.splitlines():
        line = raw.strip()
        if not name and line.startswith("versionName="):
            name = line.split("=", 1)[1].strip()
        elif not code and line.startswith("versionCode="):
            parts = line.split("=", 1)[1].split()
            code = parts[0].strip() if parts else ""
    return name, code


def _device_info_from_props(host: str, port: int, props: dict[str, str]) -> DeviceInfo:
    return DeviceInfo(
        host=host,
        port=port,
        serial=props.get("ro.serialno", "") or f"{host}:{port}",
        manufacturer=props.get("ro.product.manufacturer", ""),
        model=props.get("ro.product.model", ""),
        brand=props.get("ro.product.brand", ""),
        android_version=props.get("ro.build.version.release", ""),
        sdk_version=props.get("ro.build.version.sdk", ""),
        security_patch=props.get("ro.build.version.security_patch", ""),
    )


# ==================================================================
# adb operations (blocking; run in an executor)
# ==================================================================
def _connect(host: str, port: int) -> None:
    rc, out, err = _run_adb_blocking(["connect", f"{host}:{port}"], timeout=20)
    _check_connect_result(rc, out, err)


def _serial(host: str, port: int) -> str:
    return f"{host}:{port}"


def _pair_blocking(host: str, port: int, code: str) -> None:
    # Pass the code as an argument (modern adb) and also on stdin as a fallback
    # for builds that would otherwise prompt for it interactively.
    rc, out, err = _run_adb_blocking(
        ["pair", f"{host}:{port}", code], timeout=25, input_text=f"{code}\n"
    )
    _check_pair_result(rc, out, err)


def _probe_blocking(host: str, port: int) -> dict[str, str]:
    _connect(host, port)
    rc, out, err = _run_adb_blocking(["-s", _serial(host, port), "shell", "getprop"], timeout=20)
    props = _parse_getprop(out)
    if not props:
        raise AndroidError(f"لم تُقرأ خصائص الجهاز: {(err or out).strip()[:200]}")
    return props


def _list_apps_blocking(host: str, port: int, include_system: bool) -> list[AppInfo]:
    _connect(host, port)
    serial = _serial(host, port)
    args = ["-s", serial, "shell", "pm", "list", "packages", "-f"]
    if not include_system:
        args.insert(-1, "-3")  # 3rd-party only
    rc, out, err = _run_adb_blocking(args, timeout=25)
    if rc != 0 and not out:
        raise AndroidError(f"pm list packages فشل: {(err or '').strip()[:200]}")

    pkgs: list[tuple[str, str]] = []
    for line in out.splitlines():
        # Format: package:/data/app/pkg-x/base.apk=com.example.app
        if not line.startswith("package:"):
            continue
        body = line[len("package:") :].strip()
        if "=" not in body:
            continue
        path, pkg = body.rsplit("=", 1)
        pkgs.append((pkg.strip(), path.strip()))

    # Version lookup spawns one dumpsys per app, so bound the total work: enrich
    # up to _APP_VERSION_CAP apps and stop once _APP_ENRICH_BUDGET_S elapses.
    # Apps past the budget are still listed, just without a version string.
    apps: list[AppInfo] = []
    deadline = time.monotonic() + _APP_ENRICH_BUDGET_S
    for i, (pkg, path) in enumerate(pkgs):
        info = AppInfo(package_name=pkg, apk_path=path)
        if i < _APP_VERSION_CAP and time.monotonic() < deadline:
            try:
                _, dump, _ = _run_adb_blocking(
                    ["-s", serial, "shell", "dumpsys", "package", pkg], timeout=8
                )
                info.version_name, info.version_code = _parse_pkg_versions(dump)
            except AndroidError:
                pass
        apps.append(info)
    return apps


def _open_store_blocking(host: str, port: int, package_name: str) -> None:
    _connect(host, port)
    uri = f"market://details?id={package_name}"
    # List args (no shell): the package is already validated to [A-Za-z0-9_.],
    # so the on-device `am start` receives a single safe -d argument.
    _run_adb_blocking(
        [
            "-s",
            _serial(host, port),
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            uri,
        ],
        timeout=15,
    )


def _discover_connect_blocking(host: str) -> int | None:
    """Poll ``adb mdns services`` for ``host``'s connect port. The service can
    take a moment to appear (adb's background mDNS discovery), so retry briefly."""
    deadline = time.monotonic() + _MDNS_DISCOVER_BUDGET_S
    while True:
        _, out, _ = _run_adb_blocking(["mdns", "services"], timeout=10)
        port = _parse_mdns_connect(out, host)
        if port is not None:
            return port
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.8)


# ==================================================================
# Public async API
# ==================================================================
async def pair(host: str, port: int, code: str) -> None:
    """Pair with a phone's Wireless debugging (Android 11+). One-time per phone.

    ``host``/``port`` come from the phone's *pairing* dialog (not the main
    connect port), ``code`` is the six-digit code it shows.
    """
    _validate_host(host)
    if not _CODE_RE.match(code or ""):
        raise AndroidError("رمز الإقران يجب أن يكون ٦ أرقام.")
    if not _have_adb():
        raise AndroidError("الإقران اللاسلكي يتطلّب أداة adb المضمّنة.")
    try:
        await _in_executor(_pair_blocking, host, port, code)
    except AndroidError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"adb pair {host}:{port} failed")
        raise AndroidError(f"فشل الإقران: {exc}") from exc


async def discover_connect_port(host: str) -> int | None:
    """Best-effort: find ``host``'s Wireless-debugging connect port via adb mDNS.

    The connect port is random and changes whenever Wireless debugging restarts,
    so the UI uses this to auto-fill it instead of making the user hunt for it.
    Returns None (never raises) when discovery isn't possible.
    """
    try:
        _validate_host(host)
        if not _have_adb():
            return None
        return await _in_executor(_discover_connect_blocking, host)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mDNS discover for {host} failed: {exc}")
        return None


async def probe(host: str, port: int = 5555) -> DeviceInfo:
    """Connect and read device properties. Fast reachability + identity check."""
    _validate_host(host)
    try:
        props = await _in_executor(_probe_blocking, host, port)
    except AndroidError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"ADB probe {host}:{port} failed")
        raise AndroidError(f"Could not connect to {host}:{port}: {exc}") from exc
    return _device_info_from_props(host, port, props)


async def list_apps(host: str, port: int = 5555, include_system: bool = False) -> list[AppInfo]:
    """List installed apps on the device."""
    _validate_host(host)
    try:
        return await _in_executor(_list_apps_blocking, host, port, include_system)
    except AndroidError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"ADB list_apps {host}:{port} failed")
        raise AndroidError(f"تعذّرت قراءة التطبيقات على {host}:{port}: {exc}") from exc


async def open_play_store(host: str, port: int, package_name: str) -> None:
    """Ask Android to open the Play Store page for a package (so user can Update)."""
    if not _PACKAGE_RE.match(package_name or ""):
        raise AndroidError(f"Invalid package name: {package_name!r}")
    _validate_host(host)
    try:
        await _in_executor(_open_store_blocking, host, port, package_name)
    except AndroidError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"ADB open_play_store {host}:{port} failed")
        raise AndroidError(f"تعذّر فتح المتجر: {exc}") from exc
