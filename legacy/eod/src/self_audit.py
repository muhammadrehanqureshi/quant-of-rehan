"""The Sentinel-EOD always-on self-audit.

The Sentinel's self-audit (src/self_audit.py there) moved the deep dive
into the machine: every market morning the repo audits itself and
telegrams one verdict. This is the EOD sibling of the same law,
flavored to this repo's anatomy:

  * universe      - runs the KMIALL refresher; silent index
                    reconstitutions are caught and FIXED (green), parse
                    failures are red.
  * corporate     - verifies the stored corporate-actions map; the
                    live fetcher retired with psxterminal.com (v4.0.0),
                    so the pick rules on the last map the source
                    delivered (data/corporate_actions.json).
  * pick state    - the latest pick file and the tracker parse; a
                    corrupt state file means Monday's tracer flies
                    blind.
  * suite         - the full pytest suite must pass.
  * calendar      - weekend/holiday verdict, so silence on a closed
                    day is never mistaken for failure.

EXIT CODE IS ALWAYS 0 - a red audit must reach the owner's Telegram,
not die as a red X. Silence is the only failure mode.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _load_json(path: Path) -> tuple[object | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path.name} missing"
    except json.JSONDecodeError as exc:
        return None, f"{path.name} corrupt JSON: {exc}"


def check_universe() -> tuple[str, str]:
    import refresh_universe as ru

    try:
        records = ru.fetch_fundamentals()
        report = ru.refresh(records)
    except Exception as exc:  # noqa: BLE001 - report, never die
        return "RED", f"universe refresh failed: {exc}"
    if report["changed"]:
        detail = []
        if report["added"]:
            detail.append(f"added {report['added']}")
        if report["removed"]:
            detail.append(f"removed {report['removed']}")
        if report["flag_flips"]:
            detail.append(f"flag flips {report['flag_flips']}")
        return "GREEN", (
            f"KMIALL drift caught and FIXED ({'; '.join(detail)}) - "
            f"{report['members']} members"
        )
    return "GREEN", f"KMIALL current: {report['members']} members"


def check_corporate() -> tuple[str, str]:
    """v4.0.0: the live fetcher retired with psxterminal.com. The audit
    verifies the STORED map - the exact file run_eod's inert-layer path
    serves (load_map) when fetch_corporate_actions raises.

    v2.6.4: load_map() already unwraps the stored file's bySymbol -
    the old result.get("bySymbol", {}) double-unwrapped and audited an
    always-empty map (the 2026-10-02 false RED)."""
    try:
        import corporate_actions as ca
        by = ca.load_map()
    except Exception as exc:  # noqa: BLE001
        return "RED", f"corporate actions unreadable: {exc}"
    if not isinstance(by, dict):
        return "RED", f"corporate actions unreadable shape: {type(by).__name__}"
    carriers = sum(
        1
        for entry in by.values()
        for item in (entry if isinstance(entry, list) else [entry])
        if isinstance(item, dict) and item.get("book_closure_from")
    )
    if carriers < 10:
        return "RED", (
            f"corporate actions degenerate: only {carriers} book-closure "
            f"carriers on {len(by)} symbols"
        )
    return "GREEN", (
        f"corporate actions stored: {carriers} book-closure carriers, "
        f"{len(by)} symbols"
    )


def check_pick_state() -> tuple[str, str]:
    tracker, err = _load_json(DATA / "tracker.json")
    if err:
        return "RED", f"tracker: {err}"
    if not isinstance(tracker, (dict, list)):
        return "RED", "tracker.json unreadable shape"
    picks = sorted((DATA / "picks").glob("*.json"))
    if picks:
        _, perr = _load_json(picks[-1])
        if perr:
            return "RED", f"latest pick file: {perr}"
    return "GREEN", (
        f"pick state intact: tracker OK, {len(picks)} pick file(s)"
    )


def check_suite() -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=600, cwd=str(ROOT),
    )
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr).strip().splitlines()[-3:]
        return "RED", "test suite FAILING: " + " | ".join(tail)
    return "GREEN", "test suite green"


def check_calendar(today=None) -> tuple[str, str]:
    today = today or datetime.now(timezone.utc).date()
    if today.weekday() >= 5:
        return "GREEN", "market closed (weekend)"
    try:
        from psx_core.sessions import is_holiday  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return "RED", f"holiday module broken: {exc}"
    return "GREEN", (
        "today is a PSX holiday" if is_holiday(today)
        else "today is a trading day"
    )


def run_audit() -> dict:
    checks = [
        ("universe", check_universe()),
        ("corporate", check_corporate()),
        ("pick state", check_pick_state()),
        ("suite", check_suite()),
        ("calendar", check_calendar()),
    ]
    reds = [(name, msg) for name, (verdict, msg) in checks if verdict == "RED"]
    return {
        "verdict": "RED" if reds else "GREEN",
        "reds": reds,
        "lines": [f"{name}: {msg}" for name, (verdict, msg) in checks],
    }


def render_message(report: dict) -> str:
    header = (
        "SENTINEL-EOD SELF-AUDIT: ALL GREEN."
        if report["verdict"] == "GREEN"
        else f"SENTINEL-EOD SELF-AUDIT: {len(report['reds'])} FAILURE(S)"
    )
    return "\n".join([header, "", *report["lines"]])


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    report = run_audit()
    message = render_message(report)

    if "--print" in argv:
        print(message)
        return 0

    from telegram_notify import send

    sent = send(message)
    print(message)
    print(f"telegram delivered: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
