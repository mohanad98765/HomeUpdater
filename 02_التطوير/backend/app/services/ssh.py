"""
Linux host management over SSH (apt / dnf updates).

Uses asyncssh so blocking network I/O never stalls the event loop. Host-key
verification is disabled (``known_hosts=None``) — an accepted tradeoff for a LAN
home tool. The sudo password is fed to ``sudo -S`` over stdin, never on the
command line.
"""

from __future__ import annotations

import asyncssh

CONNECT_TIMEOUT = 12

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


async def _connect(host: str, port: int, username: str, password: str):
    try:
        return await asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None,
            connect_timeout=CONNECT_TIMEOUT,
        )
    except asyncssh.PermissionDenied as exc:
        raise SSHError("Authentication failed — check the username/password") from exc
    except Exception as exc:
        raise SSHError(f"Could not connect to {host}:{port}: {exc}") from exc


async def probe(host: str, port: int, username: str, password: str) -> dict:
    """Connect and detect the OS + package manager."""
    async with await _connect(host, port, username, password) as conn:
        result = await conn.run("cat /etc/os-release", check=False)
        kv = parse_os_release(result.stdout or "")
    os_id = (kv.get("ID") or "").lower()
    return {
        "os_name": kv.get("PRETTY_NAME") or kv.get("NAME") or "Linux",
        "os_id": os_id,
        "pkg_manager": pkg_manager_for(os_id, kv.get("ID_LIKE", "")),
    }


async def check_updates(
    host: str, port: int, username: str, password: str, pkg_manager: str
) -> dict:
    async with await _connect(host, port, username, password) as conn:
        if pkg_manager == "apt":
            result = await conn.run("apt list --upgradable 2>/dev/null", check=False)
            packages = parse_apt_upgradable(result.stdout or "")
        elif pkg_manager == "dnf":
            result = await conn.run("dnf -q check-update", check=False)
            packages = parse_dnf_updates(result.stdout or "")
        else:
            raise SSHError("Unknown package manager — re-probe the host")
    return {"total": len(packages), "packages": packages}


async def apply_updates(
    host: str, port: int, username: str, password: str, pkg_manager: str
) -> dict:
    if pkg_manager == "apt":
        cmd = "sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"
    elif pkg_manager == "dnf":
        cmd = "sudo -S -p '' dnf -y upgrade"
    else:
        raise SSHError("Unknown package manager")
    async with await _connect(host, port, username, password) as conn:
        result = await conn.run(cmd, input=(password or "") + "\n", check=False)
    return {
        "exit_status": result.exit_status,
        "succeeded": result.exit_status == 0,
        "output_tail": ((result.stdout or "") + (result.stderr or ""))[-1200:],
    }
