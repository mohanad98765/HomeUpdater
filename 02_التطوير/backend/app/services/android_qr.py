"""Pairing an Android phone by QR code, without asking anyone to read a port.

The manual flow makes a person copy three things off a phone screen — an IP, a pairing
port that changes every time, and a six-digit code that expires — into a dialog on
another machine. Android 11 added a QR path for exactly that reason: the hub shows a
code, the phone scans it, and the phone starts advertising a pairing service over mDNS.

## What is verified, and what is not

VERIFIED. The payload is ``WIFI:T:ADB;S:<name>;P:<password>;;`` — the same template in
AOSP's own QR generator and in every independent implementation of this flow. ``S`` is a
service name, ``P`` is the pairing password. Our own repository holds a real capture of
what the phone then advertises (tests/test_android.py), taken from a Samsung on this
network:

    adb-RFCW70YDHHB-hqcfQV\t_adb-tls-pairing._tcp\t192.168.3.30:34887
    adb-RFCW70YDHHB-hqcfQV\t_adb-tls-connect._tcp\t192.168.3.30:34677

NOT VERIFIED, and load-bearing if we let it be: whether a phone that scanned OUR code
advertises the name from ``S`` or, as in that capture, its own ``adb-<serial>-<random>``
guid. No source consulted answers it, and this project has been burned before by a
document describing a mechanism the code did not have (v1.13.1).

So this module does NOT match on the service name. It snapshots the pairing services
already on the network before showing the code, and treats anything that appears
AFTERWARDS as a candidate. If the instance happens to carry our name, that is used to
pick between candidates — an optimisation, never a requirement. If several phones arrive
at once, the operator is asked which one rather than being paired to a coin flip.

## What adb gives us, and what it does not

``adb mdns services`` prints exactly three fields per row: instance, service type,
address:port. No model name, no TXT record. The instance string is the only thing
distinguishing one phone from another, which is why a wrong guess has to be the
operator's to resolve.

``adb mdns check`` is not a health signal: its output is a fixed string compiled into
the binary and it succeeds whether or not any interface is usable. So a session that
finds nothing cannot say why — Windows Firewall on a Public-profile network, a phone on
another subnet, AP isolation, an IPv6-only advertisement and "the user never opened the
QR screen" all look identical from here. The copy says that instead of guessing.

A freshly started adb server reports zero services for several seconds, so the server is
warmed before the countdown starts; otherwise every session would begin with a false
"nothing found".
"""

from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from loguru import logger

from .android import (
    AndroidError,
    _have_adb,
    _in_executor,
    _run_adb_blocking,
    parse_mdns_rows,
)

PAIRING_SERVICE = "_adb-tls-pairing._tcp"
CONNECT_SERVICE = "_adb-tls-connect._tcp"

# Android's QR pairing screen does not stay open forever, and a live pairing password is
# a credential. Two minutes is longer than the walk to the phone and short enough that a
# forgotten dialog stops being an open door.
SESSION_TTL_SECONDS = 120
POLL_INTERVAL_SECONDS = 1.5


@dataclass
class PairingSession:
    """One QR pairing attempt. In memory only — never persisted, never logged."""

    id: str
    service_name: str
    password: str
    payload: str
    expires_at: datetime
    # Pairing services already advertising before we showed the code. Anything not in
    # here is something that happened because of us.
    known_instances: set[str] = field(default_factory=set)
    status: str = "waiting"  # waiting | choose | pairing | paired | failed | expired
    candidates: list[dict] = field(default_factory=list)
    device: dict | None = None
    error: str = ""
    # Set when the failure has a known cause the operator can act on, so the UI can
    # offer the remedy instead of a status word.
    diagnosis: str = ""

    def public(self) -> dict:
        """What the UI may see. The password is inside ``payload`` because the QR is
        useless without it; nothing else exposes it, and there is no way to read a
        session back after it ends."""
        return {
            "id": self.id,
            "payload": self.payload,
            "status": self.status,
            "expires_at": self.expires_at.isoformat(),
            "seconds_left": max(0, int((self.expires_at - datetime.now(UTC)).total_seconds())),
            "candidates": [
                {"instance": c["instance"], "address": c["address"], "port": c["port"]}
                for c in self.candidates
            ],
            "device": self.device,
            "error": self.error,
            "diagnosis": self.diagnosis,
        }


# One at a time, deliberately. Two live pairing passwords on one network is a footgun,
# and the operator has one phone in hand.
_session: PairingSession | None = None
_task: asyncio.Task | None = None


def current() -> PairingSession | None:
    return _session


def _new_password() -> str:
    """Six digits, like the code the phone shows in the manual flow."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _new_service_name() -> str:
    """Our label inside the QR. Random so two hubs on one network cannot collide, and
    prefixed so a person reading an mDNS dump can tell where it came from."""
    tail = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"homeupdater-{tail}"


def build_payload(service_name: str, password: str) -> str:
    """The AOSP template. Both fields are generated here from a fixed alphabet, so
    there is nothing to escape and no way for outside input to reach this string."""
    return f"WIFI:T:ADB;S:{service_name};P:{password};;"


# One module is what a camera has to resolve, and the count of modules decides how big
# each one can be. Measured for this payload:
#
#     level   version   modules+border   px/module at 300px
#     L       3         37               8.11
#     Q       4         41               7.32
#     H       5         45               6.67
#
# L is the right trade here. Error correction buys recovery from damage and occlusion;
# a code displayed on a clean screen for twenty seconds has neither, so paying 11% of
# module size for 25% recovery makes the code harder to read in exchange for robustness
# it will never use.
QR_ERROR_LEVEL = "l"
# 37 modules x 8 = 296px, an exact integer multiple. Sizing the symbol to a non-multiple
# puts every module edge mid-pixel, and the renderer anti-aliases it to grey — which is
# precisely what a binariser struggles with.
QR_SCALE = 8


def render_qr_svg(payload: str) -> str:
    """An inline SVG, generated where the password is generated.

    Rendered on the backend rather than in the browser so the pairing password appears
    in exactly one response, and so this costs the frontend bundle nothing.

    ``shape-rendering="crispEdges"`` is added because segno does not set it: the enlarged
    view scales the symbol by a viewport fraction, which cannot be an integer multiple,
    and without this every module edge softens into grey at exactly the moment the
    operator is holding a camera to the screen.
    """
    import segno

    svg = segno.make(payload, error=QR_ERROR_LEVEL).svg_inline(
        scale=QR_SCALE, dark="#000000", light="#ffffff"
    )
    return svg.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)


def _pairing_snapshot() -> set[str]:
    """Instances already advertising a pairing service, so we can ignore them."""
    try:
        _rc, out, _err = _run_adb_blocking(["mdns", "services"], timeout=10)
    except AndroidError:
        return set()
    return {r["instance"] for r in parse_mdns_rows(out) if r["service"] == PAIRING_SERVICE}


def _warm_adb_server() -> None:
    """A cold adb server reports zero services for several seconds. Starting it before
    the countdown means an empty result means something."""
    try:
        _run_adb_blocking(["start-server"], timeout=25)
    except AndroidError as exc:
        logger.warning(f"adb start-server before QR pairing: {exc}")


def _new_pairing_rows(known: set[str]) -> list[dict]:
    try:
        _rc, out, _err = _run_adb_blocking(["mdns", "services"], timeout=10)
    except AndroidError:
        return []
    return [
        r
        for r in parse_mdns_rows(out)
        if r["service"] == PAIRING_SERVICE and r["instance"] not in known
    ]


def _pair_blocking(address: str, port: int, password: str) -> None:
    from .android import _check_pair_result

    rc, out, err = _run_adb_blocking(
        ["pair", f"{address}:{port}", password], timeout=30, input_text=f"{password}\n"
    )
    _check_pair_result(rc, out, err)


def _connect_port_for(address: str) -> int | None:
    """The connect port the phone advertises after pairing. adb auto-connects to
    ``adb-tls-connect`` services by default, so this is for reporting the device to the
    UI rather than for establishing the link."""
    deadline = time.monotonic() + 12.0
    while True:
        try:
            _rc, out, _err = _run_adb_blocking(["mdns", "services"], timeout=10)
        except AndroidError:
            return None
        for row in parse_mdns_rows(out):
            if row["service"] == CONNECT_SERVICE and row["address"] == address:
                return row["port"]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.8)


async def start() -> PairingSession:
    """Begin a session: warm adb, snapshot the network, mint a password, show a code."""
    global _session, _task
    if not _have_adb():
        raise AndroidError("الإقران بالرمز يتطلّب أداة adb المضمّنة.")
    await cancel()  # one at a time

    await _in_executor(_warm_adb_server)
    known = await _in_executor(_pairing_snapshot)

    name, password = _new_service_name(), _new_password()
    session = PairingSession(
        id=secrets.token_urlsafe(12),
        service_name=name,
        password=password,
        payload=build_payload(name, password),
        expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS),
        known_instances=known,
    )
    _session = session
    # Never the payload and never the password: this line goes to a file on disk.
    logger.info(f"QR pairing session started ({len(known)} pairing services already present)")
    _task = asyncio.create_task(_watch(session))
    return session


async def _watch(session: PairingSession) -> None:
    """Poll for a pairing service that appeared because of us, then pair with it."""
    try:
        while session.status == "waiting":
            if datetime.now(UTC) >= session.expires_at:
                session.status = "expired"
                # An expired session is the moment to say WHY, because by now this
                # failure has a known cause and a known remedy. mDNS is the fragile
                # part of Android's design: the phone announces a random port and the
                # host must hear it. Measured on the first customer network — the phone
                # answers a ping in 40ms and sends zero mDNS packets in sixty seconds —
                # and reported again from a workplace network, where client isolation
                # and separate VLANs make multicast blocking the norm rather than the
                # exception. Leaving the operator with "expired" and nothing else is
                # what turned six attempts into six dead ends.
                session.diagnosis = "no_announcement"
                logger.info(
                    "QR pairing session expired unused — nothing advertised; on a "
                    "network that does not carry mDNS this is expected, and pairing "
                    "by code is the path that does not need it"
                )
                return
            rows = await _in_executor(_new_pairing_rows, session.known_instances)
            if rows:
                # If the phone did adopt the name from the QR, that is the one. If it
                # advertised its own guid — which is what our only real capture shows —
                # fall back to "whatever appeared after we started".
                exact = [r for r in rows if session.service_name in r["instance"]]
                chosen = exact or rows
                if len(chosen) > 1:
                    # Two phones at once. Pairing with a coin flip would hand our
                    # password to the wrong one.
                    session.candidates = chosen
                    session.status = "choose"
                    return
                await _pair_with(session, chosen[0])
                return
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a dead watcher must be visible in the UI
        logger.exception("QR pairing watcher failed")
        session.status = "failed"
        session.error = str(exc)


async def _pair_with(session: PairingSession, row: dict) -> None:
    session.status = "pairing"
    address, port = row["address"], row["port"]
    try:
        await _in_executor(_pair_blocking, address, port, session.password)
    except AndroidError as exc:
        session.status = "failed"
        session.error = str(exc)
        logger.warning(f"QR pairing failed against {address}: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        session.status = "failed"
        session.error = str(exc)
        logger.exception("QR pairing raised")
        return

    connect_port = await _in_executor(_connect_port_for, address)
    session.device = {"host": address, "port": connect_port, "instance": row["instance"]}
    session.status = "paired"
    # The password has done its job; drop it so a stale session object cannot leak it.
    session.password = ""
    session.payload = ""
    logger.info(f"QR pairing succeeded with {address} (connect port {connect_port})")


async def choose(instance: str) -> PairingSession:
    """The operator picked which phone, when more than one arrived at once."""
    session = _session
    if session is None or session.status != "choose":
        raise AndroidError("لا توجد جلسة إقران تنتظر اختيارًا.")
    match = next((c for c in session.candidates if c["instance"] == instance), None)
    if match is None:
        raise AndroidError("لم يعد هذا الجهاز معروضًا. أعد المحاولة.")
    session.candidates = []
    await _pair_with(session, match)
    return session


async def cancel() -> None:
    """End the session and forget the password. Called on cancel, on a new session, and
    when the dialog closes — a pairing code left live is a code someone else can use."""
    global _session, _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if _session is not None:
        _session.password = ""
        _session.payload = ""
    _session, _task = None, None


def reset_for_tests() -> None:
    global _session, _task
    _session, _task = None, None
