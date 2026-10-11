#!/usr/bin/env python3
"""Register (or remove) the local KMIALL scanner task on Windows.

Owner order 2026-10-11: scan the whole KMIALL universe every 4 minutes, in
market hours only. The registered task therefore fires ONLY inside the PSX
session, and its triggers are derived from the one session law in
src/data/sessions.py (SO-8), never typed in twice:

    Mon-Thu   09:32 to 15:30   every 4 minutes   one band
    Friday    09:17 to 12:00   every 4 minutes   first band
    Friday    14:32 to 16:30   every 4 minutes   second band, after the break
    Mon-Thu   15:47            once              finalize, after the close
    Friday    16:47            once              finalize, after the close

Nothing at all is registered for the pre-market window (09:00 to 09:15), the
Friday midday break, the evening, the night, or the weekend. The tick still
refuses to scan outside MARKET by itself (src/data/sessions.py,
`is_scan_window`), so the triggers are the schedule and the runtime check is the
guarantee; neither depends on the other being right, and a hand-run tick is
still safe.

Why the task is registered from an XML definition rather than with
`schtasks /sc MINUTE /mo 4`: the simple form fires around the clock for ever
and relies entirely on the tick to pause, which is exactly what the owner asked
to be rid of. Only the XML form can express per-weekday windows, so the
definition is written out and imported. A fallback keeps the scan alive (at the
owner's cadence, all day) if the import is ever refused.

The task is registered with an ABSOLUTE interpreter path and an absolute script
path, and the tick computes the repository root from its own file location, so
it does not depend on a working directory that Task Scheduler would otherwise
have to be told about.

    python scripts/install_kmiall_tick.py             # create / replace
    python scripts/install_kmiall_tick.py --remove    # delete
    python scripts/install_kmiall_tick.py --show      # query current definition
    python scripts/install_kmiall_tick.py --print     # print the command only
    python scripts/install_kmiall_tick.py --print-xml # print the task XML only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import sessions  # noqa: E402

TASK = "quant-of-rehan-kmiall-tick"
TICK_SCRIPT = ROOT / "scripts" / "kmiall_tick.py"
XML_FILE = ROOT / "data" / "task-kmiall-tick.xml"

#: The finalize fires a couple of minutes before its post-market window closes
#: (15:49 Monday to Thursday, 16:49 on Friday), which is where the GitHub
#: Actions crons put it too: 15:47 and 16:47 PKT.
FINALIZE_MARGIN_MINUTES = 2

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday")
FRIDAY_NAME = "Friday"


def windowless_interpreter() -> Path:
    """The console-free interpreter beside this one, or this one as a fallback.

    Started with python.exe, a console program, Task Scheduler opened a console
    and a Windows Terminal window on every fire in the owner's own session,
    which is the flash he reported on 2026-10-11. pythonw.exe is the same
    interpreter built without a console, so nothing is drawn. A build without
    pythonw still has to run, so the fallback is the current interpreter and the
    caller says out loud that a window will flash.
    """
    windowless = Path(sys.executable).with_name("pythonw.exe")
    if windowless.is_file():
        return windowless
    print("note: pythonw.exe not found next to python.exe; registering "
          "python.exe, which will flash a console window on every fire",
          file=sys.stderr)
    return Path(sys.executable)


def _minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def _hhmm(hm: tuple[int, int]) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


def _clock_text(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def session_triggers(interval_minutes: float | None = None) -> list[dict]:
    """The task's triggers, derived from the session law (SO-8).

    One repeating trigger per band, firing at the owner's cadence for exactly
    the band's own length, plus one fire per trading day in the post-market
    window for the finalize. Every window below is half-open and comes from
    src/data/sessions.py, so a change to the exchange's hours moves the task
    with it.

    Each entry is a dict with: name, days (Task Scheduler day names), start
    ("HH:MM"), every_minutes (0 for a single fire), duration_minutes, and
    inside (the session band or window it belongs to, for the tests and the
    printed summary).
    """
    interval = int(interval_minutes or config.TICK_INTERVAL_MINUTES)
    if interval < 1:
        raise ValueError("the scan cadence must be at least one minute")

    def band(name: str, days: tuple[str, ...], opens: tuple[int, int],
             closes: tuple[int, int]) -> dict:
        span = _minutes(closes) - _minutes(opens)
        return {
            "name": name,
            "days": days,
            "start": _hhmm(opens),
            "every_minutes": interval,
            "duration_minutes": span,
            "inside": f"{_hhmm(opens)}-{_hhmm(closes)}",
        }

    def finalize(name: str, days: tuple[str, ...],
                 window: tuple[tuple[int, int], tuple[int, int]]) -> dict:
        at = _minutes(window[1]) - FINALIZE_MARGIN_MINUTES
        margin = FINALIZE_MARGIN_MINUTES
        return {
            "name": name,
            "days": days,
            "start": _clock_text(at),
            "every_minutes": 0,
            "duration_minutes": 0,
            "inside": f"{_hhmm(window[0])}-{_hhmm(window[1])} (finalize, "
                      f"{margin} minutes before it closes)",
        }

    return [
        band("Mon-Thu session", WEEKDAY_NAMES,
             sessions.WEEKDAY_OPEN, sessions.WEEKDAY_CLOSE),
        band("Friday session one", (FRIDAY_NAME,),
             sessions.FRIDAY_OPEN, sessions.FRIDAY_FIRST_CLOSE),
        band("Friday session two", (FRIDAY_NAME,),
             sessions.FRIDAY_SECOND_OPEN, sessions.FRIDAY_CLOSE),
        finalize("Mon-Thu finalize", WEEKDAY_NAMES,
                 (sessions.POST_MARKET_OPEN, sessions.POST_MARKET_CLOSE)),
        finalize("Friday finalize", (FRIDAY_NAME,),
                 (sessions.FRIDAY_POST_MARKET_OPEN,
                  sessions.FRIDAY_POST_MARKET_CLOSE)),
    ]


def _repetition_xml(trigger: dict) -> str:
    """The <Repetition> block for a repeating trigger, or nothing for one fire."""
    if not trigger["every_minutes"]:
        return ""
    return (
        "\n      <Repetition>"
        f"\n        <Interval>PT{trigger['every_minutes']}M</Interval>"
        f"\n        <Duration>PT{trigger['duration_minutes']}M</Duration>"
        # A pass that runs a few seconds past the band edge must finish and be
        # logged, not be torn down by the scheduler.
        "\n        <StopAtDurationEnd>false</StopAtDurationEnd>"
        "\n      </Repetition>"
    )


def task_xml(triggers: list[dict] | None = None,
             interpreter: Path | None = None,
             script: Path | None = None,
             start_date: str | None = None) -> str:
    """The task definition, as XML, from the triggers and the absolute paths.

    Task Scheduler reads the repetition interval as an ISO 8601 duration, so
    the cadence and the band length are converted here rather than written out
    by hand: a task that claims "every 4 minutes for 5 hours 58 minutes" can
    only ever fire inside 09:32 to 15:30 on the days the trigger names.
    """
    triggers = session_triggers() if triggers is None else triggers
    interpreter = interpreter or windowless_interpreter()
    script = script or TICK_SCRIPT
    from datetime import datetime, timedelta

    day = (datetime.strptime(start_date, "%Y-%m-%d").date() if start_date
           else sessions.now_karachi().date())
    # A weekly trigger whose boundary is in the past simply advances to the
    # next matching day, so one date for all five triggers is enough.
    boundary_date = day - timedelta(days=7)

    blocks = []
    for trigger in triggers:
        days = "".join(f"<{name}/>" for name in trigger["days"])
        blocks.append(
            "    <CalendarTrigger>"
            f"\n      <StartBoundary>{boundary_date.isoformat()}T"
            f"{trigger['start']}:00</StartBoundary>"
            "\n      <Enabled>true</Enabled>"
            f"\n      <ScheduleByWeek>"
            f"\n        <DaysOfWeek>{days}</DaysOfWeek>"
            "\n        <WeeksInterval>1</WeeksInterval>"
            "\n      </ScheduleByWeek>"
            f"{_repetition_xml(trigger)}"
            "\n    </CalendarTrigger>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Author>Mr. Rehan</Author>\n"
        "    <Description>KMIALL scan, every 4 minutes inside the PSX session "
        "only (owner order 2026-10-11). Triggers are derived from "
        "src/data/sessions.py.</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n" + "\n".join(blocks) + "\n  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        # One tick at a time: the tick has its own lock as well, and IgnoreNew
        # means a slow pass cannot be piled on by the next trigger.
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        # A machine that was asleep at the fire runs it on wake. The tick then
        # decides from the session law whether there is anything to do, so a
        # late fire is either a real scan or a logged pause.
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <IdleSettings>\n"
        "      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
        "      <RestartOnIdle>false</RestartOnIdle>\n"
        "    </IdleSettings>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{interpreter}</Command>\n"
        f'      <Arguments>"{script}"</Arguments>\n'
        f"      <WorkingDirectory>{ROOT}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def write_xml(path: Path | None = None, **kwargs) -> Path:
    """Write the task definition where schtasks expects to find it.

    Task Scheduler wants the file in UTF-16, which is also what the XML
    declaration says, so the encoding here is deliberate and not a default.
    """
    target = path or XML_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(task_xml(**kwargs), encoding="utf-16")
    return target


def install_command(xml_path: Path) -> list[str]:
    """The schtasks command that imports the session-windowed definition."""
    return ["schtasks", "/create", "/tn", TASK, "/xml", str(xml_path), "/f"]


def create_command() -> list[str]:
    """The fallback command: the same task, every N minutes, all day.

    Kept because an import can be refused (a locked-down machine, a policy that
    forbids XML task definitions). The owner's cadence is preserved and the tick
    itself still refuses to scan outside MARKET, so the scanner keeps working
    even then, at the cost of the pointless fires the XML form removes.
    """
    interval = int(config.TICK_INTERVAL_MINUTES)
    action = f'"{windowless_interpreter()}" "{TICK_SCRIPT}"'
    return [
        "schtasks", "/create", "/tn", TASK,
        "/tr", action,
        "/sc", "MINUTE", "/mo", str(interval),
        "/rl", "LIMITED",
        "/f",
    ]


def run(argv: list[str]) -> int:
    print("running:", " ".join(argv))
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"could not run schtasks: {type(exc).__name__}: {exc}")
        return 5
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if output:
        print(output)
    if error:
        print(error, file=sys.stderr)
    if result.returncode != 0:
        print(f"schtasks exit {result.returncode}. If this is an access error, "
              f"create the task once from an elevated shell, or open Task "
              f"Scheduler and import:\n  {XML_FILE}")
    return result.returncode


def install() -> int:
    """Register the session-windowed task, falling back to the simple form."""
    xml_path = write_xml()
    print(f"task definition written: {xml_path}")
    for trigger in session_triggers():
        cadence = (f"every {trigger['every_minutes']} minutes"
                   if trigger["every_minutes"] else "once")
        print(f"  {trigger['name']:18s} {'/'.join(trigger['days']):26s} "
              f"at {trigger['start']} {cadence}, "
              f"inside {trigger['inside']}")
    code = run(install_command(xml_path))
    if code == 0:
        return 0
    print("\nthe XML import failed; falling back to the all-day cadence "
          "definition. The tick still refuses to scan outside the session, "
          "but it will fire all day.", file=sys.stderr)
    return run(create_command())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="install the KMIALL tick task")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true",
                       help="delete the scheduled task")
    group.add_argument("--show", action="store_true",
                       help="query the scheduled task as it stands")
    group.add_argument("--print", dest="print_only", action="store_true",
                       help="print the schtasks command without running it")
    group.add_argument("--print-xml", dest="print_xml", action="store_true",
                       help="print the task definition without registering it")
    group.add_argument("--print-fallback", dest="print_fallback",
                       action="store_true",
                       help="print the all-day fallback command")
    args = parser.parse_args(argv)

    if not TICK_SCRIPT.is_file():
        print(f"missing tick script: {TICK_SCRIPT}", file=sys.stderr)
        return 2

    if args.print_xml:
        print(task_xml(), end="")
        return 0
    if args.print_fallback:
        print(" ".join(create_command()))
        return 0
    if args.print_only:
        print(" ".join(install_command(XML_FILE)))
        return 0
    if args.remove:
        return run(["schtasks", "/delete", "/tn", TASK, "/f"])
    if args.show:
        return run(["schtasks", "/query", "/tn", TASK, "/v", "/fo", "LIST"])
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
