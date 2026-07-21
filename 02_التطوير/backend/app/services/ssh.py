"""
Linux host management over SSH (apt / dnf updates).

Uses asyncssh so blocking network I/O never stalls the event loop. Host-key
verification is disabled (``known_hosts=None``) — an accepted tradeoff for a LAN
home tool. The sudo password is fed to ``sudo -S`` over stdin, never on the
command line.
"""

from __future__ import annotations

import time

import asyncssh

from .adaptive_timeout import AdaptiveNetworkTimeout

CONNECT_TIMEOUT = 12  # cold-start / fallback connect timeout (seconds)
# Command execution bounds. connect_timeout only covers the handshake, so without
# these a remote command (apt waiting on a dpkg lock, a dropped peer) hangs the
# request forever — and, via the advisor's shared update slot, 409s every later op.
CMD_TIMEOUT = 60  # probe / check: quick commands
APPLY_TIMEOUT = 1800  # apply: apt/dnf upgrade can legitimately run for a while
# The connect timeout is learned per host:port: a LAN Raspberry Pi and a distant
# host no longer share one fixed value. Floor kept generous (SSH handshake + auth
# needs headroom); ceiling bounds the worst wait.
_CONNECT_FLOOR = 5.0
_CONNECT_CEIL = 30.0
_MAX_ESTIMATORS = 256  # bound growth across many hosts (FIFO eviction)
_CONNECT_ESTIMATORS: dict[str, AdaptiveNetworkTimeout] = {}


def _connect_estimator(host: str, port: int) -> AdaptiveNetworkTimeout:
    key = f"{host}:{port}"
    est = _CONNECT_ESTIMATORS.get(key)
    if est is None:
        if len(_CONNECT_ESTIMATORS) >= _MAX_ESTIMATORS:
            _CONNECT_ESTIMATORS.pop(next(iter(_CONNECT_ESTIMATORS)))  # drop oldest
        est = AdaptiveNetworkTimeout(
            rto_min=_CONNECT_FLOOR, rto_max=_CONNECT_CEIL, rto_initial=CONNECT_TIMEOUT
        )
        _CONNECT_ESTIMATORS[key] = est
    return est


def capture_estimators() -> dict:
    """Snapshot the per host:port connect estimators for persistence."""
    return {key: est.to_dict() for key, est in _CONNECT_ESTIMATORS.items()}


def restore_estimators(data: dict) -> None:
    """Warm-start the connect estimators from a persisted snapshot."""
    for key, snap in (data or {}).items():
        host, sep, port = key.rpartition(":")
        if not sep:
            continue
        try:
            _connect_estimator(host, int(port)).load_dict(snap)
        except (ValueError, TypeError):
            continue


# os-release ID / ID_LIKE -> package manager
_APT_IDS = {"debian", "ubuntu", "raspbian", "linuxmint", "pop", "kali", "devuan"}
_DNF_IDS = {"fedora", "rhel", "centos", "rocky", "almalinux", "ol", "amzn"}


class SSHError(RuntimeError):
    """Raised when an SSH operation fails (connect, auth, or command)."""


def parse_os_release(text: str) -> dict:
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.split("=", 1)
            kv[key.strip()] = val.strip().strip('"')
    return kv


def pkg_manager_for(os_id: str, id_like: str = "") -> str:
    ids = {(os_id or "").lower()} | set((id_like or "").lower().split())
    if ids & _APT_IDS:
        return "apt"
    if ids & _DNF_IDS:
        return "dnf"
    return ""


def parse_apt_upgradable(text: str) -> list[dict]:
    """Parse `apt list --upgradable`: 'pkg/repo new arch [upgradable from: old]'."""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if "/" not in line or line.startswith("Listing"):
            continue
        name = line.split("/", 1)[0]
        parts = line.split()
        available = parts[1] if len(parts) > 1 else ""
        current = ""
        if "upgradable from:" in line:
            current = line.split("upgradable from:", 1)[1].strip().rstrip("]").strip()
        out.append({"name": name, "current": current, "available": available})
    return out


def parse_dnf_updates(text: str) -> list[dict]:
    """Parse `dnf check-update`: 'name.arch  version  repo'."""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        parts = line.split()
        if (
            len(parts) >= 3
            and "." in parts[0]
            and not line.startswith(("Last metadata", "Obsoleting", "Security"))
        ):
            out.append({"name": parts[0], "current": "", "available": parts[1]})
    return out


async def _connect(
    host: str, port: int, username: str, password: str, known_host_key: str | None = None
):
    """Open an SSH connection.

    Trust-on-first-use host-key verification: when ``known_host_key`` (an OpenSSH
    public-key line captured on the first connect) is given, asyncssh verifies the
    server presents that exact key during the handshake — **before** the password
    is sent — and raises on mismatch, defeating an on-path MITM. When it is None
    (first connect / a host added before this feature) we accept the key and the
    caller captures it.
    """
    if known_host_key:
        known_hosts = asyncssh.import_known_hosts(f"{host} {known_host_key}\n")
    else:
        known_hosts = None
    est = _connect_estimator(host, port)
    start = time.monotonic()
    try:
        conn = await asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=known_hosts,
            connect_timeout=est.current(),
            # Detect a silently dropped LAN peer instead of hanging (~60s).
            keepalive_interval=15,
            keepalive_count_max=4,
        )
    except asyncssh.PermissionDenied as exc:
        raise SSHError("Authentication failed — check the username/password") from exc
    except asyncssh.HostKeyNotVerifiable as exc:
        raise SSHError(
            "مفتاح مضيف SSH تغيّر عمّا كان محفوظاً — احتمال هجوم MITM. "
            "إن كان التغيير مقصوداً (أُعيد تثبيت الخادم) احذف الجهاز وأضِفه من جديد."
        ) from exc
    except Exception as exc:
        raise SSHError(f"Could not connect to {host}:{port}: {exc}") from exc
    est.on_sample(time.monotonic() - start)  # full success: a real connect-time sample
    return conn


async def _run_cmd(conn, cmd: str, timeout: float, **kwargs):
    """conn.run bounded by a timeout, with dropped-peer/timeout errors normalized.

    asyncssh's connect_timeout does not bound command execution, so every command
    gets an explicit deadline here — otherwise a stuck command hangs the request
    forever and wedges the shared update slot (409 on every later op)."""
    try:
        return await conn.run(cmd, timeout=timeout, check=False, **kwargs)
    except TimeoutError as exc:
        raise SSHError(f"SSH command timed out after {int(timeout)}s") from exc
    except asyncssh.Error as exc:
        raise SSHError(f"SSH command failed: {exc}") from exc


def _capture_host_key(conn) -> str:
    """The server's public host key as an OpenSSH line (keytype + base64)."""
    try:
        return conn.get_server_host_key().export_public_key("openssh").decode().strip()
    except Exception:
        return ""


async def probe(
    host: str, port: int, username: str, password: str, known_host_key: str | None = None
) -> dict:
    """Connect and detect the OS + package manager, and capture the host key.

    Returns ``host_key`` (the OpenSSH line) so the caller can persist it for TOFU
    verification on later connects. If ``known_host_key`` is given it is verified.
    """
    async with await _connect(host, port, username, password, known_host_key) as conn:
        host_key = _capture_host_key(conn)
        result = await _run_cmd(conn, "cat /etc/os-release", CMD_TIMEOUT)
        kv = parse_os_release(result.stdout or "")
    os_id = (kv.get("ID") or "").lower()
    return {
        "os_name": kv.get("PRETTY_NAME") or kv.get("NAME") or "Linux",
        "os_id": os_id,
        "pkg_manager": pkg_manager_for(os_id, kv.get("ID_LIKE", "")),
        "host_key": host_key,
    }


async def check_updates(
    host: str,
    port: int,
    username: str,
    password: str,
    pkg_manager: str,
    known_host_key: str | None = None,
) -> dict:
    async with await _connect(host, port, username, password, known_host_key) as conn:
        if pkg_manager == "apt":
            result = await _run_cmd(conn, "apt list --upgradable 2>/dev/null", CMD_TIMEOUT)
            packages = parse_apt_upgradable(result.stdout or "")
        elif pkg_manager == "dnf":
            result = await _run_cmd(conn, "dnf -q check-update", CMD_TIMEOUT)
            packages = parse_dnf_updates(result.stdout or "")
        else:
            raise SSHError("Unknown package manager — re-probe the host")
    return {"total": len(packages), "packages": packages}


async def apply_updates(
    host: str,
    port: int,
    username: str,
    password: str,
    pkg_manager: str,
    known_host_key: str | None = None,
) -> dict:
    if pkg_manager == "apt":
        cmd = "sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"
    elif pkg_manager == "dnf":
        cmd = "sudo -S -p '' dnf -y upgrade"
    else:
        raise SSHError("Unknown package manager")
    async with await _connect(host, port, username, password, known_host_key) as conn:
        result = await _run_cmd(conn, cmd, APPLY_TIMEOUT, input=(password or "") + "\n")
    return {
        "exit_status": result.exit_status,
        "succeeded": result.exit_status == 0,
        "output_tail": ((result.stdout or "") + (result.stderr or ""))[-1200:],
    }
