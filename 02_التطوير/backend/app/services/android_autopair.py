"""Pair a phone knowing only a six-digit code — no mDNS, no ports, no expertise.

## Why this exists

Wireless debugging pairs over a port the phone picks at random and publishes over mDNS.
Every tool assumes the host can hear that announcement. On the network this product was
built for, it cannot: the PC is on Ethernet, the phone is on Wi-Fi, and the router does
not forward multicast between them. Measured — the phone answers a ping in 40ms and
sends zero mDNS packets in sixty seconds while five arrive from other hosts. Six QR
pairing attempts failed for this reason and nothing in the app was wrong.

The response is not to teach the operator about multicast. The product is sold to people
running a shop or a home office; asking one of them to enable IGMP snooping, or to read a
random port off a phone screen, is asking them to become a network engineer to add a
phone. That is a product failure, not a user failure.

So the port is found rather than heard. It is a TCP listener on a host whose address the
app already knows from its own network scan, and unicast to that host demonstrably works.
Measured on the real phone: 20,000 ports in 16 seconds at 1,252 ports/second, with no
false positives when nothing is listening.

What the operator does now: tap "Pair device with pairing code" on the phone, and type
the six digits it shows. Nothing else.

## Why the scan is narrow and polite

Only the phone the operator picked is probed, only the range Android actually uses, and
each connection is opened and closed immediately — this is a reachability question, not
an inspection. The range is a measured fact rather than a guess: the two ports this very
phone published earlier were 34887 (pairing) and 34677 (connect).
"""

from __future__ import annotations

import asyncio
import re
import time

from loguru import logger

from .android import AndroidError, _have_adb, _in_executor, _run_adb_blocking, _validate_host

# Android's wireless-debugging listeners land in the ephemeral range. Kept as one
# constant so the bench in tools/ and the service cannot drift apart.
PORT_RANGE = (30000, 50000)
# Measured on the real phone across four settings: 800/0.6s took 16.0s per sweep,
# 2500/0.3s takes 6.2s, and pushing to 4000 gets slower again. 6 seconds is what makes
# QR pairing feel automatic — nineteen sweeps fit inside the two-minute window, so the
# port is found within moments of the scan rather than at the end of a long wait.
SCAN_CONCURRENCY = 2500
PROBE_TIMEOUT = 0.3
CODE_RE = re.compile(r"^\d{6}$")


async def _port_open(host: str, port: int, sem: asyncio.Semaphore) -> int | None:
    async with sem:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=PROBE_TIMEOUT
            )
        except Exception:  # noqa: BLE001 — closed or filtered is the common answer
            return None
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return port


async def find_open_ports(
    host: str, first: int | None = None, last: int | None = None
) -> list[int]:
    """Every open TCP port on ``host`` in the range Android uses, lowest first."""
    _validate_host(host)
    lo = first if first is not None else PORT_RANGE[0]
    hi = last if last is not None else PORT_RANGE[1]
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    started = time.monotonic()
    found = await asyncio.gather(*(_port_open(host, p, sem) for p in range(lo, hi)))
    ports = sorted(p for p in found if p)
    logger.info(
        f"port scan {host}:{lo}-{hi} found {len(ports)} open in "
        f"{time.monotonic() - started:.1f}s"
    )
    return ports


def _pair_blocking(host: str, port: int, code: str) -> tuple[bool, str]:
    """One pairing attempt. Returns (ok, message) rather than raising: during a scan
    most candidates are simply the wrong port, and that is not an error."""
    rc, out, err = _run_adb_blocking(
        ["pair", f"{host}:{port}", code], timeout=25, input_text=f"{code}\n"
    )
    text = f"{out}\n{err}".strip()
    return (rc == 0 and "uccessfully paired" in text), text


async def pair_with_code(host: str, code: str, on_progress=None) -> dict:
    """Find the pairing port, pair, connect, and report the phone.

    ``on_progress`` receives short status keys the UI turns into sentences; it is never
    given raw adb output, because the operator this is written for cannot use it.
    """
    _validate_host(host)
    if not CODE_RE.match(code or ""):
        raise AndroidError("رمز الإقران يجب أن يكون ٦ أرقام.")
    if not _have_adb():
        raise AndroidError("الإقران يتطلّب أداة adb المضمّنة.")

    def progress(step: str, **extra):
        if on_progress:
            on_progress(step, **extra)

    progress("scanning")
    ports = await find_open_ports(host)
    if not ports:
        raise AndroidError(
            "لم يُعثر على منفذ إقران مفتوح على هذا الجهاز. تأكّد أن شاشة «إقران جهاز "
            "برمز الإقران» ما زالت مفتوحة على الهاتف — فهي تُغلق المنفذ عند الخروج منها."
        )

    progress("pairing", candidates=len(ports))
    last_message = ""
    for port in ports:
        ok, message = await _in_executor(_pair_blocking, host, port, code)
        last_message = message
        if ok:
            logger.info(f"paired with {host}:{port} by scanning (no mDNS involved)")
            progress("paired", port=port)
            return {"paired": True, "pairing_port": port, "host": host}
        # A wrong port answers something other than "successfully paired"; a wrong CODE
        # on the right port says so explicitly, and retrying other ports would only
        # burn the operator's time on a certain failure.
        if "code" in message.lower() or "authenticat" in message.lower():
            raise AndroidError(
                "الرمز غير صحيح أو انتهت صلاحيته. أغلق شاشة الإقران على الهاتف "
                "وافتحها من جديد للحصول على رمز جديد."
            )

    raise AndroidError(
        f"عُثر على {len(ports)} منفذًا مفتوحًا ولم يقبل أيٌّ منها الرمز. "
        f"غالبًا انتهت صلاحية الرمز — افتح شاشة الإقران من جديد. ({last_message[:120]})"
    )


async def find_connect_port(host: str, exclude: int | None = None) -> int | None:
    """The port to actually connect on, found the same way — by looking, not listening.

    After pairing, the phone keeps a second listener open. mDNS would name it; on a
    network that does not carry mDNS, scanning finds it just as well.
    """
    ports = await find_open_ports(host)
    for port in ports:
        if port == exclude:
            continue
        rc, out, err = await _in_executor(_run_adb_blocking, ["connect", f"{host}:{port}"], 20)
        if rc == 0 and "connected to" in f"{out}{err}".lower():
            logger.info(f"connected to {host}:{port}")
            return port
    return None
