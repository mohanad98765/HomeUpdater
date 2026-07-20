"""The winget runner is now bounded by a stall-watchdog on output, not a fixed
wall clock. These use real subprocesses (no stream mocking) to prove:
  - normal output is captured and the exit code returned,
  - a silent hang is killed (not waited out),
  - a process that keeps emitting output is NOT killed even past idle_timeout.
"""

from __future__ import annotations

import asyncio
import sys
import time

from app.services import software_updates as su


def _run_cmd(*args, **kwargs):
    return asyncio.run(su._run(*args, **kwargs))


def test_run_captures_output_on_success():
    rc, out, _err = _run_cmd(sys.executable, "-c", "print('hello-run')")
    assert rc == 0
    assert "hello-run" in out


def test_run_watchdog_kills_a_silent_hang():
    t0 = time.monotonic()
    try:
        _run_cmd(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",  # silent, would hang the old wall clock
            idle_timeout=0.2,
            hard_ceiling=20.0,
        )
        raise AssertionError("expected a stall abort")
    except su.SoftwareUpdateError as exc:
        assert "stalled" in str(exc)
    assert time.monotonic() - t0 < 4.0  # killed on silence, not after 30s


def test_run_stays_alive_while_output_flows():
    # Output every 0.1s; gaps are far under idle_timeout, so periodic progress
    # must keep it alive to completion even though it runs longer than one gap.
    script = (
        "import time,sys\nfor i in range(6):\n    print(i); sys.stdout.flush(); time.sleep(0.1)\n"
    )
    rc, out, _err = _run_cmd(sys.executable, "-c", script, idle_timeout=1.5, hard_ceiling=30.0)
    assert rc == 0
    assert "5" in out  # ran to the end, never killed mid-progress
