"""``HomeUpdater.exe --agent`` — the same binary, running as the target-side agent.

Why the same binary: a second build, a second signing step and a second update channel
would each be a place for the fleet's agents to drift out of date, and a stale agent is
worse than none. The agent is a MODE, not a product: it reuses the inventory and
Windows-Update code the hub already runs locally, so what a customer sees for their own
PC is literally the same code path as what an agent reports.

The security rules are the protocol's, enforced here on the client side too — an agent
that trusts more than the protocol allows is a hole even if the hub is correct:

* the private key is generated HERE, encrypted at rest with the app's own DPAPI-backed
  key, and never transmitted;
* the hub's TLS certificate is pinned at enrolment; a changed certificate stops the
  agent instead of silently trusting a new one;
* only enumerated commands run, and only for ids this agent itself reported — a hub
  that gets compromised cannot name an update this machine never saw;
* nothing is ever executed from a string the hub sends: there is no such field.

Not built yet, and not pretended otherwise (see 03_الوثائق/AGENT_PROTOCOL.md §5):
service installation/lifecycle, self-update, and the Session 0 consent window.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import platform
import secrets
import socket
import ssl
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from loguru import logger

from .config import get_appdata_dir
from .crypto import decrypt, encrypt
from .services.agent_auth import signing_input

CHECKIN_SECONDS = 300
# A hub that is down must not turn into a hot loop against a machine that may be
# rebooting; back off to this and no further, so recovery is still prompt.
MAX_BACKOFF_SECONDS = 3600
STATE_FILE = "agent_state.json"


class AgentError(RuntimeError):
    """Anything that makes it unsafe or impossible to continue as an agent."""


@dataclass
class AgentState:
    hub_url: str
    agent_id: str
    private_key_pem: str  # encrypted at rest
    cert_pin_sha256: str = ""  # "" for a loopback http hub (testing only)
    name: str = ""

    @property
    def key(self) -> Ed25519PrivateKey:
        from cryptography.hazmat.primitives import serialization

        raw = decrypt(self.private_key_pem).encode()
        loaded = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise AgentError("stored agent key is not Ed25519")
        return loaded


def state_path() -> Path:
    return get_appdata_dir() / STATE_FILE


def load_state() -> AgentState | None:
    file = state_path()
    if not file.exists():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        return AgentState(**data)
    except Exception as exc:  # noqa: BLE001 — a corrupt state file must be visible
        raise AgentError(f"agent state unreadable: {exc}") from exc


def save_state(state: AgentState) -> None:
    file = state_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.__dict__, indent=1), encoding="utf-8")
    tmp.replace(file)


def machine_id() -> str:
    """A stable per-machine string. Not a secret — the hub only ever sees its hash."""
    parts = [platform.node() or socket.gethostname(), platform.machine()]
    try:  # the Windows MachineGuid is the stable one; fall back if it is unreadable
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            parts.append(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:  # noqa: BLE001 — non-Windows or restricted: hostname is enough
        pass
    return "|".join(parts)


def cert_fingerprint(url: str) -> str:
    """SHA-256 of the hub's TLS certificate, for pinning at enrolment."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return ""
    host, port = parsed.hostname or "", parsed.port or 443
    der = ssl.get_server_certificate((host, port), timeout=10).encode()
    import ssl as _ssl

    return hashlib.sha256(_ssl.PEM_cert_to_DER_cert(der.decode())).hexdigest()


def _require_pin_or_loopback(url: str, pin: str) -> None:
    """A remote hub must be https AND pinned. Plain http is allowed only to loopback,
    which is what makes local testing possible without inviting a plaintext fleet."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        if not pin:
            raise AgentError("https hub requires a certificate pin")
        return
    if (parsed.hostname or "") not in {"127.0.0.1", "localhost", "::1"}:
        raise AgentError("a non-loopback hub must use https")


def sign_headers(state: AgentState, method: str, path: str, body: bytes) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat()
    nonce = secrets.token_hex(16)
    sig = state.key.sign(signing_input(state.agent_id, method, path, timestamp, nonce, body))
    return {
        "X-HU-Agent": state.agent_id,
        "X-HU-Timestamp": timestamp,
        "X-HU-Nonce": nonce,
        "X-HU-Signature": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }


def make_client(state: AgentState) -> httpx.Client:
    _require_pin_or_loopback(state.hub_url, state.cert_pin_sha256)
    if state.cert_pin_sha256:
        current = cert_fingerprint(state.hub_url)
        if current != state.cert_pin_sha256:
            # Stop, loudly. Trusting a new certificate on sight would undo the pin.
            raise AgentError(
                "hub certificate changed: pinned "
                f"{state.cert_pin_sha256[:16]}… but saw {current[:16]}… — re-enrol"
                " deliberately if this was a legitimate renewal"
            )
    return httpx.Client(base_url=state.hub_url, timeout=30.0)


# --------------------------------------------------------------------- enrol
def enrol(hub_url: str, token: str, name: str = "", client: httpx.Client | None = None):
    """First run: generate a key, redeem the token, remember who we are."""
    from cryptography.hazmat.primitives import serialization

    hub_url = hub_url.rstrip("/")
    pin = cert_fingerprint(hub_url)
    _require_pin_or_loopback(hub_url, pin)

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    owned = client is None
    http = client or httpx.Client(base_url=hub_url, timeout=30.0)
    try:
        resp = http.post(
            "/api/agents/enrol",
            json={
                "token": token,
                "machine_id": machine_id(),
                "public_key": key.public_key().public_bytes_raw().hex(),
                "name": name or platform.node(),
                "os_name": f"{platform.system()} {platform.release()}",
                "agent_version": _version(),
            },
        )
    finally:
        if owned:
            http.close()
    if resp.status_code != 200:
        raise AgentError(f"enrolment refused: {resp.status_code} {resp.text[:200]}")

    body = resp.json()
    state = AgentState(
        hub_url=hub_url,
        agent_id=body["agent_id"],
        private_key_pem=encrypt(pem),  # at rest under the app's DPAPI-backed key
        cert_pin_sha256=pin,
        name=name or platform.node(),
    )
    save_state(state)
    if body.get("requires_confirmation"):
        # The WHOLE fingerprint, grouped. The hub deliberately masks everything after
        # the first group, and asks the operator to type the last one — a challenge
        # only answerable from this screen. Printing a truncated value here would make
        # that challenge unanswerable; printing it ungrouped makes it unreadable.
        logger.warning(
            "enrolled as PENDING — an operator must confirm this fingerprint in the hub"
            f" before any command is sent: {grouped(body.get('fingerprint', ''))}"
        )
    logger.info(f"enrolled: agent_id={state.agent_id[:8]}… status={body.get('status')}")
    return state, body


def grouped(fingerprint: str) -> str:
    """``a3f19c02 b7d4e610 …`` — four groups of eight.

    Comparing two 32-character blobs by eye is how a confirmation step decays into a
    ritual click; comparing four short groups is something a human can actually do.
    """
    return " ".join(fingerprint[i : i + 8] for i in range(0, len(fingerprint), 8))


def show_id() -> str:
    """This machine's agent fingerprint — what the hub will store, computed offline.

    Two uses, both of which the product needed and did not have: minting a token bound
    to THIS machine before the agent has ever run, and recovering the confirmation
    challenge after the enrolment line has scrolled out of the console.
    """
    from .services.enrolment import fingerprint as _fp

    return grouped(_fp(machine_id()))


def _version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "0"


# ------------------------------------------------------------------- commands
async def _collect() -> tuple[int, int, list[str], list[str]]:
    """What this machine currently has. Returns (inventory, pending, ids, product_ids).

    The id lists are what makes "only ids this agent reported" enforceable: a command
    naming anything else is refused locally, so a wrong or hostile hub cannot make this
    machine act on an identifier it never saw.
    """
    from .services import software_updates, windows_updates

    products: list[str] = []
    try:
        items, _degraded = await software_updates.list_installed_software()
        products = [i.product_id for i in items]
    except Exception as exc:  # noqa: BLE001 — inventory is best-effort, never fatal
        logger.warning(f"inventory failed: {exc}")
    updates: list[str] = []
    try:
        found = await windows_updates.check_for_updates()
        updates = [u.update_id for u in found]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"update check failed: {exc}")
    return len(products), len(updates), updates, products


async def execute(command: dict, known_updates: list[str], known_products: list[str]) -> dict:
    """Run ONE enumerated command. Anything unrecognised is refused, not guessed."""
    from .services import windows_updates

    kind = command.get("kind", "")
    if kind in ("inventory", "windows_updates_check"):
        # Both are satisfied by the check-in that follows; nothing to execute.
        return {"ok": True, "summary": f"{kind} refreshed"}

    if kind == "windows_updates_install":
        ids = [str(i) for i in command.get("update_ids", [])]
        unknown = [i for i in ids if i not in known_updates]
        if unknown:
            # The hub naming an update this machine never reported is either a bug or
            # an attack; either way this agent is not the place to find out.
            return {"ok": False, "summary": f"refused: unknown update ids {unknown[:3]}"}
        result = await windows_updates.install_updates(ids)
        return {
            "ok": bool(result.get("installed")),
            "summary": f"installed {result.get('installed', 0)}/{len(ids)}",
            "reboot_required": bool(result.get("reboot_required")),
        }

    if kind == "software_upgrade":
        ids = [str(i) for i in command.get("product_ids", [])]
        unknown = [i for i in ids if i not in known_products]
        if unknown:
            return {"ok": False, "summary": f"refused: unknown product ids {unknown[:3]}"}
        from .services import software_updates

        try:
            result = await software_updates.install_many(ids)
        except Exception as exc:  # noqa: BLE001 — report the failure, never crash out
            return {"ok": False, "summary": f"upgrade failed: {exc}"}
        installed = int(result.get("installed", 0) or 0)
        return {
            "ok": installed == len(ids),
            "summary": f"upgraded {installed}/{len(ids)}",
            "reboot_required": bool(result.get("reboot_required")),
        }

    return {"ok": False, "summary": f"refused: unknown command kind {kind!r}"}


async def run_once(state: AgentState, client: httpx.Client) -> dict:
    """One check-in plus whatever it comes back with."""
    inventory, pending, update_ids, product_ids = await _collect()
    body = json.dumps(
        {
            "agent_version": _version(),
            "inventory_count": inventory,
            "pending_updates": pending,
        }
    ).encode()
    resp = client.post(
        "/api/agents/checkin",
        content=body,
        headers=sign_headers(state, "POST", "/api/agents/checkin", body),
    )
    if resp.status_code != 200:
        detail = resp.text[:200]
        if "clock_skew" in detail:
            # Named, so the operator sees WHY this machine went quiet.
            logger.error(f"check-in refused for clock skew: {detail}")
        raise AgentError(f"check-in refused: {resp.status_code} {detail}")

    data = resp.json()
    skew = data.get("clock_skew_seconds", 0)
    if abs(skew) > data.get("max_skew_seconds", 120) / 2:
        logger.warning(f"clock is {skew}s off the hub — fix time sync before it refuses us")

    for command in data.get("commands", []):
        outcome = await execute(command, update_ids, product_ids)
        result_body = json.dumps(
            {
                "command_id": command.get("id"),
                "ok": bool(outcome.get("ok")),
                "summary": str(outcome.get("summary", ""))[:2000],
                "reboot_required": bool(outcome.get("reboot_required")),
            }
        ).encode()
        client.post(
            "/api/agents/result",
            content=result_body,
            headers=sign_headers(state, "POST", "/api/agents/result", result_body),
        )
        logger.info(f"command {command.get('id')} ({command.get('kind')}): {outcome}")
    return data


async def loop(state: AgentState, interval: int = CHECKIN_SECONDS) -> None:
    backoff = interval
    while True:
        try:
            with make_client(state) as client:
                await run_once(state, client)
            backoff = interval
        except AgentError as exc:
            logger.error(f"agent: {exc}")
            backoff = min(MAX_BACKOFF_SECONDS, max(interval, backoff * 2))
        except Exception as exc:  # noqa: BLE001 — a loop that dies is a silent agent
            logger.error(f"agent check-in failed: {exc}")
            backoff = min(MAX_BACKOFF_SECONDS, max(interval, backoff * 2))
        await asyncio.sleep(backoff)


# ------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    """``--agent [--hub URL --token T] [--name N] [--once] [--show-id]``.

    With a token it enrols (first run); without one it uses the saved state. ``--once``
    performs a single check-in and exits, which is what a scheduled task would call and
    what makes the mode testable without a service. ``--show-id`` prints this machine's
    fingerprint and exits without touching the network or the saved state.
    """
    args = list(argv if argv is not None else sys.argv[1:])

    def opt(flag: str) -> str | None:
        return (
            args[args.index(flag) + 1]
            if flag in args and args.index(flag) + 1 < len(args)
            else None
        )

    hub, token, name = opt("--hub"), opt("--token"), opt("--name") or ""
    once = "--once" in args

    if "--show-id" in args:
        # Deliberately before everything else: no network, no state written, nothing
        # enrolled. Safe to run on a machine that is not (or no longer) an agent.
        print(show_id())  # noqa: T201 — this IS the output of this mode
        return 0

    try:
        state = load_state()
        if token:
            if not hub:
                raise AgentError("--token requires --hub")
            state, _body = enrol(hub, token, name)
        if state is None:
            raise AgentError("not enrolled: pass --hub and --token once")
        if once:
            with make_client(state) as client:
                asyncio.run(run_once(state, client))
        else:
            asyncio.run(loop(state))
    except AgentError as exc:
        logger.error(f"agent: {exc}")
        return 2
    except KeyboardInterrupt:
        return 0
    return 0
