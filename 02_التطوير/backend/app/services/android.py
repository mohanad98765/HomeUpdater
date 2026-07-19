"""
Android device integration via ADB over TCP/IP.

Uses the pure-Python `adb-shell` library so we don't depend on the
official adb.exe binary. Devices must be reachable at IP:port (usually
5555). The user enables "Wireless debugging" (Android 11+) or plugs the
phone in and runs `adb tcpip 5555` once beforehand.

Public API:
  - connect(host, port)            -> AdbDevice
  - get_device_info(host, port)    -> dict of properties
  - list_packages(host, port)      -> list of installed 3rd-party packages
  - open_play_store(host, port, pkg) -> ask Android to open the Play page

RSA key pair is stored in %APPDATA%\\HomeUpdater\\adb_keys\\ and generated
on first use. The phone will prompt "Allow USB debugging?" the first time
a new host connects — the user must tap Allow.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..config import get_appdata_dir

# A valid Android package name is dot-separated alphanumerics/underscores only.
# Enforced before it is ever interpolated into an `am start` shell command, to
# block shell injection through the /apps/{package_name}/open path parameter.
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")


# ==================================================================
# ADB key management
# ==================================================================
def _key_paths() -> tuple[Path, Path]:
    """Return (private_key_path, public_key_path). Creates the parent dir."""
    key_dir = get_appdata_dir() / "adb_keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    return key_dir / "adbkey", key_dir / "adbkey.pub"


def _ensure_keys() -> tuple[str, str]:
    """Generate an RSA key pair on first run. Returns (pub, priv) strings."""
    from adb_shell.auth.keygen import keygen  # type: ignore[import-not-found]

    priv_path, pub_path = _key_paths()
    if not priv_path.exists() or not pub_path.exists():
        logger.info(f"Generating ADB key pair at {priv_path}")
        keygen(str(priv_path))  # creates both files
    return pub_path.read_text().strip(), priv_path.read_text().strip()


def _signer():
    """Return a PythonRSASigner bound to our key pair."""
    from adb_shell.auth.sign_pythonrsa import PythonRSASigner  # type: ignore[import-not-found]

    pub, priv = _ensure_keys()
    return PythonRSASigner(pub, priv)


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
# Low-level: connect + run shell
# ==================================================================
def _connect_blocking(host: str, port: int, timeout: float = 10.0):
    """Blocking connect. Runs in an executor."""
    from adb_shell.adb_device import AdbDeviceTcp  # type: ignore[import-not-found]

    device = AdbDeviceTcp(host, port, default_transport_timeout_s=timeout)
    device.connect(rsa_keys=[_signer()], auth_timeout_s=15.0)
    return device


def _shell_blocking(device, cmd: str, timeout: float = 20.0) -> str:
    """Run a shell command; return stdout as a string."""
    try:
        return device.shell(cmd, read_timeout_s=timeout) or ""
    except Exception as exc:
        raise AndroidError(f"shell '{cmd[:60]}' failed: {exc}") from exc


async def _in_executor(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# ==================================================================
# Public async API
# ==================================================================
async def probe(host: str, port: int = 5555) -> DeviceInfo:
    """Connect, read device properties, disconnect. Fast reachability check."""

    def _work():
        device = _connect_blocking(host, port)
        try:
            props = {}
            for prop in (
                "ro.serialno",
                "ro.product.manufacturer",
                "ro.product.model",
                "ro.product.brand",
                "ro.build.version.release",
                "ro.build.version.sdk",
                "ro.build.version.security_patch",
            ):
                props[prop] = _shell_blocking(device, f"getprop {prop}").strip()
            return props
        finally:
            try:
                device.close()
            except Exception:
                pass

    try:
        props = await _in_executor(_work)
    except AndroidError:
        raise
    except Exception as exc:
        logger.exception(f"ADB probe {host}:{port} failed")
        raise AndroidError(f"Could not connect to {host}:{port}: {exc}") from exc

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


async def list_apps(host: str, port: int = 5555, include_system: bool = False) -> list[AppInfo]:
    """List installed apps on the device."""

    def _work():
        device = _connect_blocking(host, port)
        try:
            flag = "" if include_system else "-3"  # -3 = 3rd-party only
            out = _shell_blocking(device, f"pm list packages {flag} -f")
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

            # Fetch version for each package (batched via dumpsys)
            apps: list[AppInfo] = []
            for pkg, path in pkgs:
                info = AppInfo(package_name=pkg, apk_path=path)
                try:
                    dump = _shell_blocking(
                        device, f"dumpsys package {pkg} | grep version", timeout=10
                    )
                    for line in dump.splitlines():
                        line = line.strip()
                        if line.startswith("versionName="):
                            info.version_name = line.split("=", 1)[1].strip()
                        elif line.startswith("versionCode="):
                            # "versionCode=12345 minSdk=..." -> keep first token
                            info.version_code = line.split("=", 1)[1].split()[0].strip()
                except Exception:
                    pass
                apps.append(info)
            return apps
        finally:
            try:
                device.close()
            except Exception:
                pass

    return await _in_executor(_work)


async def open_play_store(host: str, port: int, package_name: str) -> None:
    """Ask Android to open the Play Store page for a package (so user can Update)."""
    if not _PACKAGE_RE.match(package_name or ""):
        raise AndroidError(f"Invalid package name: {package_name!r}")

    def _work():
        device = _connect_blocking(host, port)
        try:
            uri = f"market://details?id={package_name}"
            _shell_blocking(
                device,
                f'am start -a android.intent.action.VIEW -d "{uri}"',
            )
        finally:
            try:
                device.close()
            except Exception:
                pass

    await _in_executor(_work)
