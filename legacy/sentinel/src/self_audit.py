"""The always-on self-audit.

WHY THIS EXISTS: every defect ever found in this repo was found either
by accident or when the owner demanded a deep dive. That is the wrong
place for verification to live - in a human's memory, on a human's
schedule. This module moves the audit INTO the machine: every market
morning, before the bell, the repo audits itself and sends one Telegram
verdict. Green means every known failure class is currently closed.
Anything else names exactly what is broken.

A report that does not arrive is itself the alarm - it means the audit
or its delivery chain is down.

WHAT IT CHECKS (each maps to a real incident from the ledger):
  * universe freshness   - KSE reconstituted KMIALL silently (2026-09-20,
                           NNAR + SOYASUP missed). The refresher runs
                           here; drift is FIXED and reported, parse
                           failures are red.
  * corporate actions    - book-closure/results data must be fresh
                           (stale copies = trading into ex-dividend
                           drops). 72h ceiling covers the weekend.
  * test suite           - the full pytest suite must pass. Tests that
                           only pass sometimes are tests that lie.
  * book integrity       - portfolio.json parses, positions carry the
                           fields the exits need.
  * delivery dedup       - notified.json parses; a corrupt ledger means
                           re-sent or lost signals.
  * holiday verdict      - today's session shape, so silence on a
                           holiday is never mistaken for failure.

EXIT CODE IS ALWAYS 0 - a red audit must reach the owner's Telegram,
not die as a red X in an email. The workflow-level alarm is silence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CORP_MAX_AGE_H = 72.0  # one session-day of staleness allowed; weekend-proof


def _load_json(path: Path) -> tuple[object | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path.name} missing"
    except json.JSONDecodeError as exc:
        return None, f"{path.name} corrupt JSON: {exc}"


def check_universe() -> tuple[str, str]:
    """Refresh the KMIALL list; drift is a catch (green), errors are red."""
    import refresh_universe as ru

    try:
        records = ru.fetch_fundamentals()
    except Exception as exc:  # noqa: BLE001 - the audit reports, never dies
        return "RED", f"universe source unreachable: {exc}"
    try:
        report = ru.refresh(records)
    except Exception as exc:  # noqa: BLE001
        return "RED", f"universe refresh refused: {exc}"
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


def _corp_veto_enabled() -> bool:
    """True when the entry engine actually consumes corporate actions."""
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable config: assume OFF
        return False
    return bool(cfg.get("corporate_actions_veto_enabled", False))


def check_corporate_actions(path: Path | None = None) -> tuple[str, str]:
    """Freshness only binds while the veto consumes the file.

    The notice source retired with psxterminal.com (v4.0.0). With
    corporate_actions_veto_enabled False the stale copy is a known,
    acknowledged state - not a failure (2026-10-01: the audit had
    been red forever, crying wolf over a source that no longer
    exists).
    """
    if not _corp_veto_enabled():
        return (
            "GREEN",
            "corporate actions inert (veto off, source retired v4.0.0)",
        )
    data, err = _load_json(path or DATA / "corporate_actions.json")
    if err:
        return "RED", err
    fetched = str(data.get("fetchedAt", ""))
    try:
        when = datetime.fromisoformat(fetched)
    except ValueError:
        return "RED", f"corporate_actions fetchedAt unreadable: {fetched!r}"
    age_h = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if age_h > CORP_MAX_AGE_H:
        return "RED", f"corporate actions stale: {age_h:.0f}h old"
    return "GREEN", f"corporate actions fresh ({age_h:.0f}h old)"


def check_suite() -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=900, cwd=str(ROOT),
    )
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr).strip().splitlines()[-3:]
        return "RED", "test suite FAILING: " + " | ".join(tail)
    return "GREEN", "test suite green"


def check_book(path: Path | None = None) -> tuple[str, str]:
    data, err = _load_json(path or DATA / "portfolio.json")
    if err:
        return "RED", err
    positions = data if isinstance(data, list) else data.get("positions", [])
    if not isinstance(positions, list):
        return "RED", "portfolio shape unreadable"
    open_pos = [p for p in positions if p.get("exit_price") in (None, "")]
    for p in open_pos:
        # The book stores target_price (Position dataclass field); the
        # delivery card's renderer calls it profit_target_price. Accept
        # either name - the audit must flag a REAL gap, not a naming one.
        # (Sep-21 false alarm: every open position looked "missing".)
        for field in ("symbol", "entry_price"):
            if p.get(field) in (None, ""):
                return "RED", (
                    f"open position {p.get('symbol', '?')} missing {field}"
                )
        if p.get("target_price") in (None, "") and p.get(
            "profit_target_price"
        ) in (None, ""):
            return "RED", (
                f"open position {p.get('symbol', '?')} missing target_price"
            )
    state = f"{len(open_pos)} open / {len(positions)} total"
    return "GREEN", f"book intact: {state}"


def check_notified(path: Path | None = None) -> tuple[str, str]:
    _, err = _load_json(path or DATA / "notified.json")
    if err:
        return "RED", err
    return "GREEN", "delivery dedup ledger intact"


PENNY_FLOOR_FALLBACK = 10.0  # Rule 27: no entry under Rs 10 (the KEL lesson)


def _penny_floor() -> float:
    """The live engine floor, with a hard fallback so the audit never
    dies on an import - the tripwire must arm every morning."""
    try:
        from decision_engine import DecisionConfig

        return float(
            getattr(DecisionConfig(), "min_entry_price", PENNY_FLOOR_FALLBACK)
        )
    except Exception:  # noqa: BLE001 - audit never dies on import
        return PENNY_FLOOR_FALLBACK


def check_penny_calls(
    path: Path | None = None, today=None
) -> tuple[str, str]:
    """Rule 27 tripwire: today's own decisions log vs the penny floor.

    The engine refuses entries under the floor (KEL at Rs 6-7 taught
    that); this makes any violation IMPOSSIBLE TO MISS in the log the
    bot itself writes, so a mystery "KEL call" on the owner's phone is
    machine-proven in or out of the bot within one audit cycle. A
    missing log means no calls were made today - green."""
    floor = _penny_floor()
    log = path or ROOT / "logs" / "decisions.jsonl"
    try:
        entries = [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except FileNotFoundError:
        return (
            "GREEN",
            f"penny tripwire: no calls today - no bot-side KEL-style "
            f"call possible (Rule 27 floor {floor:g} armed)",
        )
    except (json.JSONDecodeError, OSError) as exc:
        return "RED", f"decisions log unreadable: {exc}"

    if today is None:
        today = datetime.now(timezone(timedelta(hours=5))).date()
    elif isinstance(today, str):
        today = datetime.strptime(today, "%Y-%m-%d").date()

    violations = []
    entered = 0
    for rec in entries:
        if rec.get("action") != "ENTER":
            continue
        at = str(rec.get("at", ""))
        try:
            when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.astimezone(timezone(timedelta(hours=5))).date() != today:
            continue
        entered += 1
        price = rec.get("price")
        if isinstance(price, (int, float)) and price < floor:
            violations.append(
                f"{rec.get('symbol', '?')} @ Rs {price:g} "
                f"(floor {floor:g})"
            )
    if violations:
        return "RED", "penny tripwire: entry below Rule 27 floor - " + \
            "; ".join(violations)
    return (
        "GREEN",
        f"penny tripwire: {entered} entry(ies) today, all >= floor "
        f"{floor:g} - no bot-side KEL-style call possible",
    )


def check_calendar(today=None) -> tuple[str, str]:
    today = today or datetime.now(timezone.utc).date()
    if today.weekday() >= 5:
        return "GREEN", "market closed (weekend)"
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from psx_core.sessions import is_holiday
    except Exception as exc:  # noqa: BLE001
        return "RED", f"holiday module broken: {exc}"
    return "GREEN", (
        "today is a PSX holiday" if is_holiday(today)
        else "today is a trading day"
    )


def run_audit() -> dict:
    checks = [
        ("universe", check_universe()),
        ("corporate", check_corporate_actions()),
        ("suite", check_suite()),
        ("book", check_book()),
        ("delivery", check_notified()),
        ("penny", check_penny_calls()),
        ("calendar", check_calendar()),
    ]
    reds = [(name, msg) for name, (verdict, msg) in checks if verdict == "RED"]
    return {
        "verdict": "RED" if reds else "GREEN",
        "reds": reds,
        "lines": [
            f"{name}: {msg}"
            for name, (verdict, msg) in checks
        ],
    }


def render_message(report: dict) -> str:
    header = (
        "SELF-AUDIT: ALL GREEN - every known failure class is closed."
        if report["verdict"] == "GREEN"
        else f"SELF-AUDIT: {len(report['reds'])} FAILURE(S) NEED ATTENTION"
    )
    lines = [header, ""]
    lines.extend(report["lines"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    report = run_audit()
    message = render_message(report)

    if "--print" in argv:
        print(message)
        return 0

    from notify import send_telegram

    sent = send_telegram(message)
    print(message)
    print(f"telegram delivered: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
