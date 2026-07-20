"""Endpoint connect/operation timeouts are now adaptive/per-operation:
  - SSH connect_timeout is a per-host:port RTO (a LAN Pi != a distant host),
  - WinRM splits the quick probe/check from the minutes-long upgrade-all.
"""

from __future__ import annotations

import asyncio

from app.services import ssh
from app.services import winrm_hosts as wr
from app.services.ssh import _connect_estimator


def test_ssh_connect_estimator_is_per_hostport_and_wan_clamped():
    a = _connect_estimator("192.168.1.5", 22)
    a2 = _connect_estimator("192.168.1.5", 22)
    b = _connect_estimator("192.168.1.5", 2222)
    assert a is a2  # reused per host:port
    assert a is not b
    assert a.current() == ssh.CONNECT_TIMEOUT  # cold start == old fixed value
    for _ in range(50):
        a.on_sample(0.05)  # fast LAN host answers quickly
    assert a.current() == ssh._CONNECT_FLOOR  # clamped to a sane floor, never ~0


def test_winrm_apply_uses_the_longer_upgrade_op_timeout(monkeypatch):
    captured = {}

    async def fake_run_ps(*_args, op_timeout=wr.OP_TIMEOUT):
        captured["op_timeout"] = op_timeout
        return (0, "done", "")

    monkeypatch.setattr(wr, "_run_ps", fake_run_ps)
    asyncio.run(wr.apply_updates("h", 5985, "u", "p"))
    assert captured["op_timeout"] == wr.UPGRADE_OP_TIMEOUT
    assert wr.UPGRADE_OP_TIMEOUT > wr.OP_TIMEOUT


def test_winrm_probe_keeps_the_short_default_op_timeout(monkeypatch):
    captured = {}

    async def fake_run_ps(*_args, op_timeout=wr.OP_TIMEOUT):
        captured["op_timeout"] = op_timeout
        return (0, "HOSTNAME=PC\nWINGET=True", "")

    monkeypatch.setattr(wr, "_run_ps", fake_run_ps)
    asyncio.run(wr.probe("h", 5985, "u", "p"))
    assert captured["op_timeout"] == wr.OP_TIMEOUT
