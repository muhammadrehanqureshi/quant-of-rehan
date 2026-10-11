#!/usr/bin/env python3
"""Verify the market-signals system end to end, and say what is NOT proven.

Rebuild 2026-10-10. One command that answers "is this thing actually working,
and how do I know?" It checks the parts that can silently rot:

  1. CONFIG      the hard limits are what they are supposed to be: paper only,
                 live trading off, one trade a day, a +2% target, one universe.
  2. TESTS       the whole suite, run as a subprocess with its real exit code.
  3. UNIVERSE    the tracked KMIALL snapshot resolves and has a fingerprint.
  4. RELAY       the live Cloudflare relay: health and pairing, the published
                 signal card and HOW OLD it is, the market card, the frozen
                 research gate, and that an unauthenticated read is refused.
  5. LOCAL STATE the forward-state files, the session journal, the tick log and
                 any stale lock left behind by a crashed tick.
  6. AI PRIOR    whether the trained model is active, its holdout AUC, and the
                 session the daily panel it was fed actually reaches.
  7. SCHEDULER   whether the Windows task that drives the 4-minute scanner is
                 registered, its last result and its next run.

Every check reports PASS, WARN, FAIL or SKIP. A SKIP always carries its reason:
a check that could not run is never counted as a pass.

Note on the relay client: this uses `requests`, not urllib. Cloudflare's browser
integrity check answers urllib's default user agent with HTTP 403 and the body
"error code: 1010", which looks exactly like a broken relay and is not.

Usage:
    python scripts/verify_market_signals.py                # offline + local
    python scripts/verify_market_signals.py --live         # also dial the relay
    python scripts/verify_market_signals.py --tests        # include the suite
    python scripts/verify_market_signals.py --json out.json
Exit codes: 0 = no failures, 1 = at least one FAIL, 2 = the script itself broke.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI_UTC_OFFSET_HOURS, close_time, is_market_open, is_trading_day,
    now_karachi,
)

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
TASK_NAME = "quant-of-rehan-kmiall-tick"


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, section: str, check: str, status: str, detail: str = "") -> None:
        self.rows.append({"section": section, "check": check,
                          "status": status, "detail": detail})
        marker = {PASS: "ok  ", WARN: "warn", FAIL: "FAIL", SKIP: "skip"}[status]
        print(f"[{marker}] {section:<10} {check:<34} {detail}")

    def count(self, status: str) -> int:
        return sum(1 for row in self.rows if row["status"] == status)

    @property
    def failures(self) -> list[dict]:
        return [row for row in self.rows if row["status"] == FAIL]


# --------------------------------------------------------------------- helpers

def env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def relay_base() -> str | None:
    configured = os.environ.get("RELAY_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    path = ROOT / "data" / "relay_url.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().rstrip("/")
    return None


def admin_token() -> str | None:
    token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    return token or env_file().get("RELAY_ADMIN_TOKEN") or None


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def last_trading_day(today: date) -> date:
    probe = today
    for _ in range(30):
        if is_trading_day(probe):
            return probe
        probe = probe.fromordinal(probe.toordinal() - 1)
    return today


# ---------------------------------------------------------------------- checks

def check_config(report: Report) -> None:
    s = "CONFIG"
    snap = config.config_snapshot()
    report.add(s, "paper trading enabled", PASS if config.PAPER_TRADING_ENABLED else FAIL,
               str(config.PAPER_TRADING_ENABLED))
    report.add(s, "live trading disabled", PASS if not snap["live_trading_enabled"] else FAIL,
               f"live={snap['live_trading_enabled']}")
    report.add(s, "one trade per day", PASS if config.MAX_TRADES_PER_DAY == 1 else FAIL,
               str(config.MAX_TRADES_PER_DAY))
    report.add(s, "+2.0% target", PASS if abs(config.TARGET_PCT - 0.02) < 1e-9 else FAIL,
               f"{config.TARGET_PCT * 100:.2f}%")
    report.add(s, "score weights sum to 1",
               PASS if abs(sum(config.SCORE_WEIGHTS.values()) - 1.0) < 1e-9 else FAIL,
               str(round(sum(config.SCORE_WEIGHTS.values()), 6)))
    report.add(s, "karachi clock pinned to UTC+5",
               PASS if KARACHI_UTC_OFFSET_HOURS == 5 else FAIL,
               f"UTC+{KARACHI_UTC_OFFSET_HOURS}",
)
    report.add(s, "AI prior routing", PASS,
               f"tie-break={config.AI_TIE_BREAK_ENABLED} band={config.AI_TIE_BAND:g} "
               f"veto={config.AI_GATE_ENABLED} reject<={config.AI_REJECT_PERCENTILE:.0%}")
    report.add(s, "tick cadence", PASS,
               f"every {config.TICK_INTERVAL_MINUTES:g} min, warmup "
               f"{config.TICK_WARMUP_MINUTES:g} min")


def check_tests(report: Report, enabled: bool) -> None:
    s = "TESTS"
    if not enabled:
        report.add(s, "suite", SKIP, "not requested (pass --tests)")
        return
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                                cwd=str(ROOT), capture_output=True, text=True,
                                timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        report.add(s, "suite", FAIL, f"could not run: {type(exc).__name__}")
        return
    tail = [line for line in (result.stdout or "").splitlines() if line.strip()]
    summary = tail[-1] if tail else ""
    report.add(s, "suite exit code",
               PASS if result.returncode == 0 else FAIL,
               f"exit {result.returncode}")
    report.add(s, "suite summary",
               PASS if result.returncode == 0 else FAIL, summary[:110])


def check_universe(report: Report) -> None:
    s = "UNIVERSE"
    universe = ROOT / "src" / "data" / "universe_kmiall.json"
    payload = read_json(universe)
    if not payload:
        report.add(s, "snapshot readable", FAIL, f"missing or unreadable: {universe.name}")
        return
    shariah = sorted({str(row["symbol"]).strip().upper() for row in payload
                      if row.get("isShariahCompliant") is True
                      and "KMIALLSHR" in row.get("listedIn", [])
                      and row.get("symbol")})
    report.add(s, "shariah KMIALL resolves", PASS if shariah else FAIL,
               f"{len(shariah)} symbols")
    try:
        from scripts.intraday_pipeline import universe_fingerprint

        report.add(s, "universe fingerprint", PASS,
                   universe_fingerprint(shariah)[:16])
    except Exception as exc:  # noqa: BLE001
        report.add(s, "universe fingerprint", SKIP, f"{type(exc).__name__}")


def check_relay(report: Report, live: bool) -> None:
    s = "RELAY"
    base = relay_base()
    if not live:
        report.add(s, "live checks", SKIP, "not requested (pass --live)")
        return
    if not base:
        report.add(s, "relay url", FAIL, "no RELAY_URL and no data/relay_url.txt")
        return
    try:
        import requests
    except ImportError:
        report.add(s, "http client", FAIL, "requests is not installed")
        return
    token = admin_token()
    if not token:
        report.add(s, "admin token", SKIP, "no RELAY_ADMIN_TOKEN in env or .env")
    report.add(s, "relay url", PASS, base)

    def get(route: str, auth: bool = True, timeout: int = 25):
        headers = {"x-admin-token": token} if (auth and token) else {}
        try:
            return requests.get(base + route, headers=headers, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return type("R", (), {"status_code": None, "text": f"{type(exc).__name__}: {exc}"})()

    health = get("/health", auth=False)
    if health.status_code != 200:
        report.add(s, "health", FAIL, f"HTTP {health.status_code} {health.text[:80]}")
    else:
        payload = json.loads(health.text)
        report.add(s, "health", PASS, f"paired={payload.get('paired')} "
                                     f"market_open={payload.get('market_open')}")
        report.add(s, "relay clock", PASS, str(payload.get("karachi_now")))
        nxt = payload.get("next_event") or {}
        report.add(s, "next session event", PASS,
                   f"{nxt.get('event')} at {nxt.get('at_pk')}")
        expected_open = payload.get("market_open")
        actual = is_market_open()
        report.add(s, "session state agrees with the local clock",
                   PASS if expected_open == actual else FAIL,
                   f"relay={expected_open} local={actual}")

    if token:
        signals = get("/signals")
        if signals.status_code != 200:
            report.add(s, "signal card readable", FAIL, f"HTTP {signals.status_code}")
        else:
            text = json.loads(signals.text).get("signals", "")
            first = text.splitlines()[0] if text else ""
            report.add(s, "signal card readable", PASS, first[:80])
            stamp = None
            for token_part in first.replace("(", " ").replace(")", " ").split():
                try:
                    stamp = datetime.fromisoformat(token_part).date()
                    break
                except ValueError:
                    continue
            if stamp is None:
                report.add(s, "signal card is dated", WARN,
                           "the published card carries no parseable date")
            else:
                # Measured in TRADING SESSIONS, not calendar days: a Wednesday
                # card is two sessions behind on a Saturday, and a closed market
                # does not excuse an old verdict. The reference is the last
                # COMPLETED session, so a trading day that has not reached its
                # close yet counts back one.
                today = now_karachi()
                reference = last_trading_day(today.date())
                if reference == today.date():
                    close_hm = close_time(reference)
                    if (today.hour, today.minute) < close_hm:
                        reference = last_trading_day(
                            reference.fromordinal(reference.toordinal() - 1))
                behind = 0
                probe = reference
                while probe > stamp and behind < 40:
                    behind += 1
                    probe = last_trading_day(probe.fromordinal(probe.toordinal() - 1))
                report.add(s, "signal card freshness",
                           PASS if behind == 0 else WARN,
                           f"{stamp.isoformat()}, {behind} trading session(s) behind "
                           f"the last completed session ({reference.isoformat()})")

        market = get("/market")
        report.add(s, "market card", PASS if market.status_code == 200 else FAIL,
                   f"HTTP {market.status_code}")
        gate = get("/research/gate")
        if gate.status_code == 200:
            g = json.loads(gate.text).get("gate", {})
            report.add(s, "research gate readable", PASS,
                       f"status={g.get('research_status')} eligible={g.get('eligible')} "
                       f"live={g.get('live_signal_enabled')}")
            report.add(s, "gate keeps live signals off",
                       PASS if not g.get("live_signal_enabled") else FAIL,
                       f"live_signal_enabled={g.get('live_signal_enabled')}")
        else:
            report.add(s, "research gate readable", WARN, f"HTTP {gate.status_code}")
        history = get("/research/history")
        if history.status_code == 200:
            sessions = json.loads(history.text).get("sessions") or []
            last = sessions[-1].get("date") if sessions else None
            report.add(s, "research history", PASS, f"{len(sessions)} sessions, last {last}")
        else:
            report.add(s, "research history", WARN, f"HTTP {history.status_code}")

    anon = get("/research/observations", auth=False)
    report.add(s, "unauthenticated read refused",
               PASS if anon.status_code in (401, 403) else FAIL,
               f"HTTP {anon.status_code}")


def check_local_state(report: Report) -> None:
    s = "STATE"
    forward = ROOT / "data" / "forward"
    observation = read_json(forward / "observation.json")
    if observation is None:
        report.add(s, "latest observation", WARN,
                   "no data/forward/observation.json in this checkout")
    else:
        report.add(s, "latest observation", PASS,
                   f"{observation.get('date')} {observation.get('slot')} "
                   f"status={observation.get('status')}")
        report.add(s, "observation carries data quality",
                   PASS if observation.get("data_quality") else FAIL,
                   f"coverage={(observation.get('data_quality') or {}).get('coverage')}")

    state = read_json(forward / "session_state.json")
    if state is None:
        report.add(s, "session state", WARN, "no session_state.json yet")
    else:
        report.add(s, "session state", PASS,
                   f"{state.get('day')} state={state.get('state')} "
                   f"trades={state.get('trades_today')} scans={state.get('scans')}")

    journal = ROOT / config.SESSION_JOURNAL_FILE
    if journal.is_file():
        lines = [line for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        report.add(s, "session journal", PASS, f"{len(lines)} records")
    else:
        report.add(s, "session journal", WARN, "no journal yet")

    lock = ROOT / "data" / "tick.lock"
    if lock.is_file():
        held = read_json(lock) or {}
        report.add(s, "tick lock", WARN,
                   f"a lock file exists (pid {held.get('pid')}, slot {held.get('slot')})")
    else:
        report.add(s, "tick lock", PASS, "not held")

    log = ROOT / "logs" / "kmiall_tick.log"
    if log.is_file():
        tail = [line for line in log.read_text(encoding="utf-8", errors="replace")
                .splitlines() if line.strip()][-1:]
        report.add(s, "tick log", PASS, (tail[0][:95] if tail else "empty"))
    else:
        report.add(s, "tick log", WARN, "no logs/kmiall_tick.log yet")


def check_ai(report: Report) -> None:
    s = "AI"
    try:
        from src.signals import ai_model
    except Exception as exc:  # noqa: BLE001
        report.add(s, "module", FAIL, f"{type(exc).__name__}: {exc}")
        return
    status = ai_model.status()
    if not status.get("artifact_exists"):
        report.add(s, "artifact", FAIL, status.get("reason", "missing"))
        return
    report.add(s, "artifact", PASS, status["artifact"])
    report.add(s, "feature contract", PASS, f"{len(status['features'])} features")
    report.add(s, "active", PASS if status.get("active") else WARN,
               status.get("reason", ""))
    if status.get("holdout_auc") is not None:
        report.add(s, "holdout AUC", PASS,
                   f"{status['holdout_auc']:.4f} on {status.get('holdout_rows')} rows "
                   f"(trained {status.get('trained_at')})")

    cache = read_json(ROOT / "data" / "forward" / "daily_features.json")
    if cache is None:
        report.add(s, "live prior cache", SKIP, "not built yet (first in-session tick builds it)")
        return
    as_of = cache.get("panel_as_of")
    report.add(s, "live prior cache", PASS,
               f"{len(cache.get('probabilities') or {})} symbols from panel {as_of}")
    if as_of:
        try:
            panel_day = date.fromisoformat(str(as_of))
        except ValueError:
            report.add(s, "prior panel freshness", WARN, f"unparseable panel date {as_of!r}")
            return
        sessions_behind = 0
        probe = last_trading_day(now_karachi().date())
        while probe > panel_day and sessions_behind < 40:
            sessions_behind += 1
            probe = last_trading_day(probe.fromordinal(probe.toordinal() - 1))
        report.add(s, "prior panel freshness",
                   PASS if sessions_behind <= 1 else WARN,
                   f"panel {as_of} is {sessions_behind} trading session(s) behind; "
                   f"refresh with the EOD download before relying on the prior")


def check_scheduler(report: Report) -> None:
    s = "SCHEDULER"
    if os.name != "nt":
        report.add(s, "windows task", SKIP, "not a Windows host")
        return
    try:
        result = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME,
                                 "/fo", "LIST", "/v"],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        report.add(s, "windows task", FAIL, f"schtasks unavailable: {type(exc).__name__}")
        return
    if result.returncode != 0:
        report.add(s, "task registered", FAIL,
                   f"{TASK_NAME} not found; run python scripts/install_kmiall_tick.py")
        return
    report.add(s, "task registered", PASS, TASK_NAME)
    fields = {}
    for line in (result.stdout or "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields.setdefault(key.strip().lower(), value.strip())
    report.add(s, "next run", PASS, fields.get("next run time", "unknown"))
    report.add(s, "last result", PASS if fields.get("last result") == "0" else WARN,
               f"{fields.get('last result')} at {fields.get('last run time')}")


# ------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify the market signals system")
    parser.add_argument("--live", action="store_true", help="dial the relay")
    parser.add_argument("--tests", action="store_true", help="also run the suite")
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    parser.add_argument("--all", action="store_true", help="--live --tests together")
    args = parser.parse_args(argv)

    live = args.live or args.all
    tests = args.tests or args.all

    moment = now_karachi()
    print(f"verify_market_signals: {moment:%Y-%m-%d %H:%M} PKT "
          f"({'trading day' if is_trading_day(moment.date()) else 'market closed'}), "
          f"python {sys.version.split()[0]}\n")

    report = Report()
    check_config(report)
    check_tests(report, tests)
    check_universe(report)
    check_relay(report, live)
    check_local_state(report)
    check_ai(report)
    check_scheduler(report)

    print(f"\n{report.count(PASS)} pass, {report.count(WARN)} warn, "
          f"{report.count(FAIL)} fail, {report.count(SKIP)} skipped")
    for row in report.failures:
        print(f"  FAIL {row['section']}/{row['check']}: {row['detail']}")

    if args.json:
        args.json.write_text(json.dumps({
            "generated_at": moment.isoformat(timespec="seconds"),
            "checks": report.rows,
            "summary": {"pass": report.count(PASS), "warn": report.count(WARN),
                        "fail": report.count(FAIL), "skip": report.count(SKIP)},
        }, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if report.failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - the verifier must not crash silently
        print(f"verifier failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
