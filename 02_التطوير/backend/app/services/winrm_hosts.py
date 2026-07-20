"""
Remote Windows host update management over WinRM (PowerShell Remoting).

This closes the last "execution" gap for the *fleet* vision: the local machine
(the hub) is updated directly, and OTHER Windows PCs on the LAN are updated here
over WinRM. We use pywinrm (synchronous, requests-based) wrapped in
``asyncio.to_thread`` so its blocking network I/O never stalls the event loop.

Transport: default ``ntlm`` — works with a local Administrator account and
encrypts the payload even over plain HTTP (port 5985), so we don't require the
insecure ``AllowUnencrypted`` basic-auth setup. HTTPS (5986) is supported too.

Update source on the target: ``winget upgrade`` (App Installer, Win10/11). We
reuse the locale-safe winget table parser from ``software_updates`` so Arabic
Windows output is handled. winget must be resolvable in the WinRM session — see
``DEVICES.md`` (Phase 1.6) for the caveat and how to enable it on the target.

Credentials (admin username/password) are never logged and never returned.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from .software_updates import _parse_winget_table

DEFAULT_PORT = 5985
DEFAULT_HTTPS_PORT = 5986
OP_TIMEOUT = 25  # seconds — probe/check (quick round-trips)
# `winget upgrade --all` legitimately runs for minutes; give each WS-Man poll a
# longer operation window so the install path isn't the same budget as a probe.
# read_timeout is always operation_timeout + 10 (the pywinrm invariant: the HTTP
# read must outlast the server's operation window or the socket closes early).
UPGRADE_OP_TIMEOUT = 90
READ_TIMEOUT_MARGIN = 10

# PowerShell that locates winget even when it isn't on the session PATH (it lives
# under the user's WindowsApps). Emits WINGET_NOT_FOUND if truly unavailable.
_LOCATE_WINGET = r"""
$ErrorActionPreference = 'SilentlyContinue'
$wg = (Get-Command winget.exe).Source
if (-not $wg) {
  $c = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { $wg = $c.FullName }
}
if (-not $wg) {
  $c = Get-ChildItem "C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe" `
    -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($c) { $wg = $c.FullName }
}
if (-not $wg) { Write-Output 'WINGET_NOT_FOUND'; exit 3 }
"""

_PROBE_PS = r"""
$os = Get-CimInstance Win32_OperatingSystem
Write-Output ("CAPTION=" + $os.Caption)
Write-Output ("VERSION=" + $os.Version)
Write-Output ("HOSTNAME=" + $env:COMPUTERNAME)
$wg = (Get-Command winget.exe -ErrorAction SilentlyContinue).Source
if (-not $wg) {
  $c = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { $wg = $c.FullName }
}
Write-Output ("WINGET=" + [bool]$wg)
"""

_CHECK_PS = (
    _LOCATE_WINGET
    + "& $wg upgrade --include-unknown --accept-source-agreements --disable-interactivity\n"
)

_UPGRADE_PS = (
    _LOCATE_WINGET
    + "& $wg upgrade --all --include-unknown --silent "
    + "--accept-source-agreements --accept-package-agreements --disable-interactivity\n"
)


class WinRMHostError(RuntimeError):
    """Raised when a WinRM operation fails (connect, auth, or command)."""


def _endpoint(host: str, port: int, use_https: bool) -> str:
    scheme = "https" if use_https else "http"
    return f"{scheme}://{host}:{port}/wsman"


def _friendly_error(exc: Exception) -> str:
    """Map pywinrm/requests exceptions to a human-readable, non-leaky message."""
    name = exc.__class__.__name__
    msg = str(exc)
    low = msg.lower()
    if "InvalidCredentials" in name or "401" in msg or "unauthorized" in low:
        return "فشل المصادقة — تحقّق من اسم المستخدم/كلمة المرور (استخدم حساب مسؤول)."
    if (
        "ConnectionError" in name
        or "max retries" in low
        or "actively refused" in low
        or "timed out" in low
        or "no route" in low
        or "failed to establish" in low
    ):
        return (
            "تعذّر الوصول إلى WinRM على هذا الجهاز/المنفذ. "
            "هل WinRM مُفعَّل (Enable-PSRemoting) والمنفذ مفتوح؟"
        )
    return f"خطأ WinRM: {msg}"


def parse_probe(text: str) -> dict:
    """Parse the KEY=VALUE probe output into an OS summary."""
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            kv[key.strip()] = val.strip()
    return {
        "os_name": kv.get("CAPTION") or "Windows",
        "os_version": kv.get("VERSION", ""),
        "hostname": kv.get("HOSTNAME", ""),
        "has_winget": kv.get("WINGET", "").lower() == "true",
    }


def _packages_from_winget(stdout: str) -> list[dict]:
    return [
        {
            "name": p.name,
            "id": p.package_id,
            "current": p.current_version,
            "available": p.available_version,
        }
        for p in _parse_winget_table(stdout)
    ]


def _run_ps_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    use_https: bool,
    transport: str,
    script: str,
    verify_tls: bool = False,
    op_timeout: int = OP_TIMEOUT,
) -> tuple[int, str, str]:
    """Open a WinRM session and run a PowerShell script (blocking).

    Over HTTPS, ``verify_tls`` enables real certificate validation (MITM
    protection). It's off by default because home WinRM listeners usually present
    a self-signed cert; NTLM/Kerberos still message-encrypt the payload even when
    the transport cert isn't validated.
    """
    import winrm  # imported lazily so non-Windows/test envs load the module fine

    cert_validation = "validate" if (use_https and verify_tls) else "ignore"
    try:
        session = winrm.Session(
            _endpoint(host, port, use_https),
            auth=(username, password),
            transport=transport,
            server_cert_validation=cert_validation,
            operation_timeout_sec=op_timeout,
            read_timeout_sec=op_timeout + READ_TIMEOUT_MARGIN,  # invariant: read > operation
        )
        result = session.run_ps(script)
    except Exception as exc:  # noqa: BLE001 — normalize every failure to one type
        raise WinRMHostError(_friendly_error(exc)) from exc
    out = (result.std_out or b"").decode("utf-8", errors="replace")
    err = (result.std_err or b"").decode("utf-8", errors="replace")
    return result.status_code, out, err


async def _run_ps(
    host: str,
    port: int,
    username: str,
    password: str,
    use_https: bool,
    transport: str,
    script: str,
    verify_tls: bool = False,
    op_timeout: int = OP_TIMEOUT,
) -> tuple[int, str, str]:
    return await asyncio.to_thread(
        _run_ps_sync,
        host,
        port,
        username,
        password,
        use_https,
        transport,
        script,
        verify_tls,
        op_timeout,
    )


async def probe(
    host: str,
    port: int,
    username: str,
    password: str,
    use_https: bool = False,
    transport: str = "ntlm",
    verify_tls: bool = False,
) -> dict:
    """Connect and detect the OS + winget availability (verifies credentials)."""
    rc, out, err = await _run_ps(
        host, port, username, password, use_https, transport, _PROBE_PS, verify_tls
    )
    if not out.strip():
        raise WinRMHostError(err.strip() or f"فشل الفحص الأولي (رمز {rc}).")
    return parse_probe(out)


async def check_updates(
    host: str,
    port: int,
    username: str,
    password: str,
    use_https: bool = False,
    transport: str = "ntlm",
    verify_tls: bool = False,
) -> dict:
    """List app upgrades available on the remote host via winget."""
    rc, out, err = await _run_ps(
        host, port, username, password, use_https, transport, _CHECK_PS, verify_tls
    )
    if "WINGET_NOT_FOUND" in out or "WINGET_NOT_FOUND" in err:
        raise WinRMHostError(
            "winget غير متوفّر على الجهاز الهدف (أو غير قابل للوصول من جلسة WinRM). "
            "ثبّت App Installer من المتجر، أو راجع DEVICES.md."
        )
    packages = _packages_from_winget(out)
    # winget prints its table even when it exits non-zero (reboot pending, one
    # unmatched package, ...), so a non-zero rc WITH output is fine. But a
    # non-zero rc with NO parseable output means the command failed (no network,
    # source-agreement error) — don't silently report "0 updates / up to date".
    if not packages and rc != 0 and not out.strip():
        raise WinRMHostError(
            err.strip() or f"تعذّر فحص التحديثات على الجهاز الهدف (رمز winget {rc})."
        )
    return {"total": len(packages), "packages": packages}


async def apply_updates(
    host: str,
    port: int,
    username: str,
    password: str,
    use_https: bool = False,
    transport: str = "ntlm",
    verify_tls: bool = False,
) -> dict:
    """Upgrade all packages on the remote host via winget (silent)."""
    rc, out, err = await _run_ps(
        host,
        port,
        username,
        password,
        use_https,
        transport,
        _UPGRADE_PS,
        verify_tls,
        op_timeout=UPGRADE_OP_TIMEOUT,  # installs run for minutes, not seconds
    )
    if "WINGET_NOT_FOUND" in out or "WINGET_NOT_FOUND" in err:
        raise WinRMHostError("winget غير متوفّر على الجهاز الهدف.")
    logger.info(f"WinRM upgrade on {host}: exit={rc}")
    return {
        "exit_status": rc,
        "succeeded": rc == 0,
        "output_tail": ((out or "") + (err or ""))[-1500:],
    }
