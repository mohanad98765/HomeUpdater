"""The scheduled task that stops the agent from dying with its window.

The protocol was finished and the agent still went silent on the first reboot, so a
second machine meant leaving a console open on it forever. The task is the whole fix,
and the things worth testing about it are the ones that only show up on someone else's
machine: an action pointing at the wrong executable, an XML Windows rejects, a removal
that reports success on a task that is still there.

Registered for real against Windows Task Scheduler once during development (throwaway
name, elevated): trigger MSFT_TaskLogonTrigger, repetition PT15M, RunLevel Highest,
action ``…\\HomeUpdater.exe --agent --once``, then removed. These tests hold the shape
that produced it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.services import agent_task

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _xml() -> ET.Element:
    return ET.fromstring(
        agent_task.build_xml(r"C:\Program Files\HomeUpdater\HomeUpdater.exe", "PC\\dell")
    )


def test_it_calls_one_check_in_not_the_endless_loop():
    """A process that must stay alive is a process that can die silently. One check-in
    per firing means a crash costs one interval, not the machine."""
    root = _xml()
    assert root.find(".//t:Actions/t:Exec/t:Arguments", NS).text == "--agent --once"
    assert root.find(".//t:Actions/t:Exec/t:Command", NS).text.endswith("HomeUpdater.exe")


def test_it_fires_at_logon_and_keeps_firing():
    """At logon alone would check in once a day. The repetition is what makes an update
    queued at 10:05 run before lunch."""
    root = _xml()
    assert root.find(".//t:Triggers/t:LogonTrigger", NS) is not None
    interval = root.find(".//t:Triggers/t:LogonTrigger/t:Repetition/t:Interval", NS)
    assert interval.text == f"PT{agent_task.INTERVAL_MINUTES}M"
    assert (
        root.find(".//t:Triggers/t:LogonTrigger/t:Repetition/t:StopAtDurationEnd", NS).text
        == "false"
    )


def test_it_runs_elevated_as_the_person_who_is_logged_in():
    """Elevated because Windows Update needs it. As the interactive user because winget
    is a per-user execution alias — as SYSTEM the software half of the agent just fails,
    which is worse than a machine that does not check in at the lock screen."""
    root = _xml()
    assert root.find(".//t:Principals/t:Principal/t:RunLevel", NS).text == "HighestAvailable"
    assert root.find(".//t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"
    assert root.find(".//t:Principals/t:Principal/t:UserId", NS).text == "PC\\dell"


def test_it_does_not_pile_up_and_does_not_run_forever():
    root = _xml()
    assert root.find(".//t:Settings/t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    assert root.find(".//t:Settings/t:ExecutionTimeLimit", NS).text == "PT30M"
    # A laptop on battery is exactly the machine an operator forgets about.
    assert root.find(".//t:Settings/t:DisallowStartIfOnBatteries", NS).text == "false"


def test_a_name_with_xml_in_it_cannot_break_the_definition():
    xml = agent_task.build_xml("C:\\a<b>.exe", 'DOM\\"user&x"')
    ET.fromstring(xml)  # parses = the escaping held


def test_it_refuses_to_schedule_a_source_checkout(monkeypatch):
    """From source, sys.executable is a Python interpreter. A task pointing at it would
    run the wrong thing on every firing — and only ever on the customer's machine."""
    monkeypatch.delattr("sys.frozen", raising=False)
    with pytest.raises(agent_task.TaskError) as exc:
        agent_task.agent_exe()
    assert "المثبَّتة" in str(exc.value)


def test_install_hands_schtasks_an_xml_and_forces_replacement(monkeypatch, tmp_path):
    seen = {}

    def fake(args):
        seen["args"] = args
        # Read the XML the caller wrote, before install() deletes it.
        from pathlib import Path

        seen["xml"] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        return 0, "SUCCESS"

    monkeypatch.setattr(agent_task, "agent_exe", lambda: r"C:\x\HomeUpdater.exe")
    monkeypatch.setattr(agent_task, "_schtasks", fake)
    message = agent_task.install()

    assert seen["args"][0] == "/Create"
    assert "/F" in seen["args"], "re-enrolling a machine must replace, not fail"
    assert seen["args"][seen["args"].index("/TN") + 1] == agent_task.TASK_NAME
    ET.fromstring(seen["xml"])
    assert agent_task.TASK_NAME in message
    # The limitation is stated where it is created, not left to be discovered.
    assert "شاشة الدخول" in message


def test_install_reports_the_real_reason_it_failed(monkeypatch):
    monkeypatch.setattr(agent_task, "agent_exe", lambda: r"C:\x\HomeUpdater.exe")
    monkeypatch.setattr(agent_task, "_schtasks", lambda args: (1, "ERROR: Access is denied."))
    with pytest.raises(agent_task.TaskError) as exc:
        agent_task.install()
    assert "Access is denied" in str(exc.value)


def test_removing_a_task_that_is_not_there_is_not_an_error(monkeypatch):
    monkeypatch.setattr(
        agent_task, "_schtasks", lambda args: (1, "ERROR: The system cannot find the file")
    )
    assert agent_task.TASK_NAME in agent_task.remove()


def test_a_real_removal_failure_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(agent_task, "_schtasks", lambda args: (1, "ERROR: Access is denied."))
    with pytest.raises(agent_task.TaskError):
        agent_task.remove()
