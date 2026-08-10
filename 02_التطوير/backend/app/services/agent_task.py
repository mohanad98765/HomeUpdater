"""Keep the agent running on a machine nobody is watching.

The agent protocol was complete and the agent still stopped when its window closed or
the machine rebooted, so onboarding a second PC meant leaving a console open on it
forever. That is not a fleet feature; it is a demo.

A scheduled task is the whole fix, and the choices in it are all trade-offs worth
naming:

* **It runs ``--agent --once``, not the long loop.** A process that must stay alive is a
  process that can die silently. One check-in per firing means a crash costs one
  interval, and Windows restarts it without anyone noticing.
* **It runs as the logged-on user, at logon, repeating every 15 minutes.** Running as
  SYSTEM would survive an empty login screen, but winget is a per-user app execution
  alias — as SYSTEM the software-upgrade half of the agent simply fails. A machine
  sitting at the lock screen does not check in, and the operator is told so rather than
  left to discover it.
* **HighestAvailable, not a stored password.** Windows Update needs elevation; a task
  that hoards credentials to get it would be a worse answer than one that asks the user
  to be an administrator.
* **Registered from XML.** ``schtasks /Create`` on the command line cannot express a
  logon trigger with a repetition, and two separate tasks would be two things to remove.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from loguru import logger

TASK_NAME = "HomeUpdater Agent"
# Long enough that a fleet of machines does not hammer the hub, short enough that an
# operator who queues an update does not think the product ignored them.
INTERVAL_MINUTES = 15


class TaskError(RuntimeError):
    """The task could not be created, removed, or read."""


def agent_exe() -> str:
    """The executable a task should call.

    Only meaningful in a frozen build: from a source checkout ``sys.executable`` is a
    Python interpreter, and a task pointing at it would run the wrong thing on every
    firing — a failure that only shows up on someone else's machine.
    """
    if not getattr(sys, "frozen", False):
        raise TaskError("المهمّة المجدولة تُنشأ من النسخة المثبَّتة فقط (لا من شيفرة المصدر).")
    return str(Path(sys.executable))


def build_xml(exe: str, user: str, interval_minutes: int = INTERVAL_MINUTES) -> str:
    """The task definition. Kept as text on purpose: it is the contract, and it should
    be readable by whoever inherits this machine."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>HomeUpdater agent check-in. Reports this machine's updates to its hub
and runs only the commands the hub names from that report.</Description>
    <URI>\\{escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT{int(interval_minutes)}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>--agent --once</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        ["schtasks", *args],
        stdin=subprocess.DEVNULL,  # windowed builds have no valid stdin handle
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="ignore",
    )
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}".strip()


def is_installed() -> bool:
    rc, _out = _schtasks(["/Query", "/TN", TASK_NAME])
    return rc == 0


def install(interval_minutes: int = INTERVAL_MINUTES) -> str:
    """Create (or replace) the task. Returns a line describing what now exists."""
    exe = agent_exe()
    user = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}".strip("\\")
    xml = build_xml(exe, user, interval_minutes)

    # UTF-16 with a BOM: schtasks rejects a UTF-8 XML with a misleading "The task XML
    # contains a value which is incorrectly formatted", which sends whoever hits it
    # looking for a mistake in the task definition instead of in the encoding.
    handle, path = tempfile.mkstemp(suffix=".xml", prefix="homeupdater-task-")
    os.close(handle)
    try:
        Path(path).write_text(xml, encoding="utf-16")
        rc, out = _schtasks(["/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
        if rc != 0:
            raise TaskError(f"تعذّر إنشاء المهمّة المجدولة: {out[:300]}")
    finally:
        Path(path).unlink(missing_ok=True)

    logger.info(f"agent scheduled task installed for {user}, every {interval_minutes}m")
    return (
        f'أُنشئت مهمّة مجدولة باسم "{TASK_NAME}" تعمل عند تسجيل الدخول وكلّ '
        f"{interval_minutes} دقيقة للمستخدم {user}. "
        "لن يتّصل الجهاز وهو على شاشة الدخول بلا مستخدم. "
        f"للإزالة: HomeUpdater.exe --agent --remove-task"
    )


def remove() -> str:
    rc, out = _schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if rc != 0 and "cannot find" not in out.lower():
        raise TaskError(f"تعذّرت إزالة المهمّة المجدولة: {out[:300]}")
    logger.info("agent scheduled task removed")
    return f'أُزيلت المهمّة المجدولة "{TASK_NAME}".'
