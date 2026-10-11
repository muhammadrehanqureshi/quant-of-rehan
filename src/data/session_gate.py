"""The sleep gate: the first question every scheduled runner asks.

Cheap on purpose. A fire outside the PSX session must cost seconds, not
minutes, so this runs BEFORE any dependency install, before the twelve minute
bar fetch and before any portal call, and answers with one typed, loggable
decision.

Who decides
-----------
The session law in src/data/sessions.py decides whether the market is open
(SO-8). The live portal probe (src/data/market_probe.py) only ever *verifies*
it. That asymmetry is the whole design:

* a blocked, slow or unparseable portal may never silence a session the law
  says is live, so a probe failure degrades to RUN, unverified;
* an unexpected closure may never be scanned as if it were trading, so a probe
  that positively reports the exchange shut degrades to SLEEP.

Purpose: a scan sleeps outside the band, a finalize sleeps until the close
------------------------------------------------------------------------
The workflow does two different jobs on the same clock. A **scan** is only
meaningful inside a live band. A **finalize** is only meaningful *after* the
last close - its crons fire at 15:47 and 16:47 PKT, well outside every band -
so gating it on "is a band live" would silently kill the daily outcome. The
finalize path therefore runs on the session law alone, with no network call,
once the trading day has closed.

All clock times below are Asia/Karachi wall clock, pinned to a fixed
UTC+5 offset by src/data/sessions.py (SO-8); nothing here builds a market
instant of its own.

Order, first match wins
-----------------------
1. ``--force`` .................... RUN, a deliberate manual dispatch
2. weekend or PSX holiday ......... SLEEP, and no network call at all
3. purpose is finalize ............ RUN once the trading day has closed
                                    (the post-market window counts as
                                    closed), SLEEP until then
4. pre-market or post-market ...... SLEEP for a scan: the owner's order of
                                    2026-10-11 is that the quant never
                                    scans those windows
5. outside every band today ....... SLEEP (pre-open, the Friday midday break,
                                    post-close)
6. inside a band:
     probe CLOSED / SUSPENDED ..... SLEEP, the exchange is shut
     probe OPEN ................... RUN, verified
     probe UNKNOWN ................ RUN, unverified, the law decided

Usage::

    python -m src.data.session_gate --check             # scheduled scan
    python -m src.data.session_gate --check --schedule "47 10 * * 1-4"
    python -m src.data.session_gate --check --purpose finalize
    python -m src.data.session_gate --check --no-probe   # law only, no network

Exit status is always 0: a sleeping day is a correct day, not a failed build.
The verdict travels on stdout, on ``$GITHUB_OUTPUT`` (``should_run``,
``purpose``, ``slot``) and on ``$GITHUB_STEP_SUMMARY`` when those are set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.market_probe import (  # noqa: E402
    STATUS_CLOSED,
    STATUS_OPEN,
    MarketProbe,
    probe_market_state,
)
from src.data.sessions import (  # noqa: E402
    MarketPhase,
    MarketState,
    as_karachi,
    band_bounds,
    is_trading_day,
    market_phase,
    market_state_at,
    next_event,
    session_bands,
    session_window_text,
)

#: Probe states as they appear in a gate decision.
PROBE_DISABLED = "DISABLED"

#: What the fire is for.
PURPOSE_SCAN = "scan"
PURPOSE_FINALIZE = "finalize"
PURPOSES = (PURPOSE_SCAN, PURPOSE_FINALIZE)

#: The workflow's cron -> work mapping, kept here rather than only inside YAML
#: so it is unit tested (tests/test_session_gate.py) and so the gate is the one
#: authority on what a given schedule event is supposed to do. A test asserts
#: this table and .github/workflows/intraday-capture.yml never drift.
SCHEDULE_PLAN: dict[str, tuple[str, str | None]] = {
    "7 5 * * 1-5": (PURPOSE_SCAN, "10:00"),      # 10:07 PKT
    "37 6 * * 1-5": (PURPOSE_SCAN, "11:30"),     # 11:37 PKT
    "7 8 * * 1-4": (PURPOSE_SCAN, "13:00"),      # 13:07 PKT, Mon-Thu (Friday break)
    "37 9 * * 1-5": (PURPOSE_SCAN, "14:30"),     # 14:37 PKT
    "7 11 * * 5": (PURPOSE_SCAN, "16:00"),       # 16:07 PKT, Friday session 2
    "47 10 * * 1-4": (PURPOSE_FINALIZE, None),   # 15:47 PKT, after the close
    "47 11 * * 5": (PURPOSE_FINALIZE, None),     # 16:47 PKT, after the close
}


def normalise_schedule(schedule: str) -> str:
    return " ".join(str(schedule).split())


def plan_for(schedule: str) -> tuple[str, str | None]:
    """(purpose, slot) for a cron string. An unknown cron is a plain scan."""
    return SCHEDULE_PLAN.get(normalise_schedule(schedule),
                             (PURPOSE_SCAN, None))


@dataclass(frozen=True)
class GateDecision:
    """One answer to "should this scheduled fire do any work?"."""

    should_run: bool
    reason: str
    purpose: str
    slot: str | None
    phase: str
    date: str
    trading_day: bool
    law_open: bool
    probe_status: str
    probe_state: str | None
    verified: bool
    checked_at: str
    live_band: dict | None
    next_event: str | None
    forced: bool = False
    probe_note: str | None = None

    def as_dict(self) -> dict:
        return {
            "should_run": self.should_run,
            "reason": self.reason,
            "purpose": self.purpose,
            "slot": self.slot,
            "phase": self.phase,
            "date": self.date,
            "trading_day": self.trading_day,
            "law_open": self.law_open,
            "probe_status": self.probe_status,
            "probe_state": self.probe_state,
            "verified": self.verified,
            "checked_at": self.checked_at,
            "live_band": self.live_band,
            "next_event": self.next_event,
            "forced": self.forced,
            "probe_note": self.probe_note,
        }

    def summary_line(self) -> str:
        return f"{'RUN' if self.should_run else 'SLEEP'}  {self.reason}"


def _live_band(moment) -> dict | None:
    """The band that is live right now, as a printable window, or None."""
    for band in session_bands(moment.date()):
        opens, closes = band_bounds(moment.date(), band)
        if opens <= moment < closes:
            return {"open": f"{band[0][0]:02d}:{band[0][1]:02d}",
                    "close": f"{band[1][0]:02d}:{band[1][1]:02d}"}
    return None


def session_gate(moment=None, *, probe: bool | None = None,
                 force: bool = False, purpose: str = PURPOSE_SCAN,
                 slot: str | None = None) -> GateDecision:
    """Decide whether a scheduled fire should do work right now.

    `moment` defaults to the current Karachi instant. Passing it explicitly is
    how the weekend-versus-market-open transition is tested without waiting for
    a real Monday.

    `probe` defaults to config.PSX_PROBE_ENABLED, so the operator can turn the
    live verification off from the environment without a code change: with the
    probe off the session law alone decides and no socket is opened.
    """
    if probe is None:
        probe = bool(config.PSX_PROBE_ENABLED)
    now = as_karachi(moment)
    day = now.date()
    phase = market_phase(now)
    trading = is_trading_day(day)
    law_open = phase.is_live
    event, at = next_event(now)
    upcoming = None if event is None else f"{event} at {at:%Y-%m-%d %H:%M} PKT"
    live = _live_band(now)
    checked = now.isoformat(timespec="seconds")

    def decide(should_run: bool, reason: str, probe_status: str,
               probe_state: str | None = None, verified: bool = False,
               probe_note: str | None = None) -> GateDecision:
        return GateDecision(
            should_run=should_run, reason=reason, purpose=purpose, slot=slot,
            phase=phase.value, date=day.isoformat(), trading_day=trading,
            law_open=law_open, probe_status=probe_status,
            probe_state=probe_state, verified=verified, checked_at=checked,
            live_band=live, next_event=upcoming, forced=force,
            probe_note=probe_note,
        )

    if force:
        return decide(True, "forced by a deliberate manual dispatch",
                      PROBE_DISABLED)

    # 1. Cheapest rejection: no session exists today, so do not call out.
    if not trading:
        return decide(False, f"{day.isoformat()} is not a PSX trading day "
                             f"(weekend or PSX holiday)", PROBE_DISABLED)

    # 2. A finalize is about a session that has ENDED. It reads the captured
    #    bars, so it needs no network and must not be skipped for being late.
    if purpose == PURPOSE_FINALIZE:
        if phase is MarketPhase.POST_CLOSE:
            where = (" in the post-market window"
                     if market_state_at(now) is MarketState.POST_MARKET else "")
            return decide(True, f"POST_CLOSE on a trading day: finalizing "
                                f"{day.isoformat()}{where}", PROBE_DISABLED)
        return decide(False, f"{phase.value}: {day.isoformat()} has not closed "
                             f"yet ({session_window_text(day)})", PROBE_DISABLED)

    # 3. Owner order 2026-10-11: the pre-market and post-market windows are
    #    never scanned. This is deliberate and separate from the band check
    #    below, so a future change to the bands can never quietly re-enable
    #    scanning in those windows.
    scan_state = market_state_at(now)
    if scan_state is MarketState.PRE_MARKET \
            or scan_state is MarketState.POST_MARKET:
        return decide(False,
                      f"{scan_state.value}: the pre-market and post-market "
                      f"windows are never scanned (owner order 2026-10-11); "
                      f"next band {upcoming or 'unknown'}", PROBE_DISABLED)

    # 4. A scan is only meaningful inside a live band.
    if not law_open:
        return decide(False, f"{phase.value}: outside every session band "
                             f"({session_window_text(day)})", PROBE_DISABLED)

    # 5. The law says a band is live. Verify it against the exchange.
    if not probe:
        return decide(True, f"{phase.value} inside {session_window_text(day)}; "
                            f"session law only (probe disabled)", PROBE_DISABLED)

    observed: MarketProbe = probe_market_state()
    if observed.status == STATUS_CLOSED:
        return decide(
            False,
            f"portal reports the Regular market {observed.raw_state} while the "
            f"session law says {phase.value}: exchange shut, not scanning",
            observed.status, observed.raw_state, verified=True,
            probe_note=observed.note)
    if observed.status == STATUS_OPEN:
        return decide(
            True,
            f"{phase.value} inside {session_window_text(day)} and the portal "
            f"confirms the Regular market is open",
            observed.status, observed.raw_state, verified=True,
            probe_note=observed.note)

    # 6. The law is the authority and the portal could not be read. Run, and
    #    say plainly that nobody corroborated it.
    return decide(
        True,
        f"{phase.value} inside {session_window_text(day)}; portal unverified "
        f"({observed.note}), session law decides",
        observed.status, observed.raw_state, verified=False,
        probe_note=observed.note)


def _one_line(value: str) -> str:
    """GitHub's $GITHUB_OUTPUT is line delimited, so flatten the reason."""
    return " ".join(str(value).split())


def _emit(decision: GateDecision, verbose: bool = False) -> None:
    print(decision.summary_line())
    if verbose:
        print(json.dumps(decision.as_dict(), indent=2, ensure_ascii=False))

    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write("should_run="
                         f"{'true' if decision.should_run else 'false'}\n")
            handle.write(f"purpose={decision.purpose}\n")
            handle.write(f"slot={decision.slot or ''}\n")
            handle.write(f"reason={_one_line(decision.reason)}\n")
            handle.write(f"phase={decision.phase}\n")
            handle.write(f"verified={'true' if decision.verified else 'false'}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        verdict = "RUN" if decision.should_run else "SLEEP"
        probe = decision.probe_status
        if decision.probe_state:
            probe = f"{probe} ({decision.probe_state})"
        rows = [
            ("verdict", verdict),
            ("purpose", decision.purpose),
            ("reason", decision.reason),
            ("phase", decision.phase),
            ("date", decision.date),
            ("trading day", str(decision.trading_day)),
            ("probe", probe),
            ("verified", str(decision.verified)),
            ("next event", decision.next_event or "unknown"),
        ]
        body = "\n".join(f"| {key} | {value} |" for key, value in rows)
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"## Session gate: {verdict}\n\n"
                         "| field | value |\n|---|---|\n" + body + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sleep outside the PSX session (SO-8 session law)")
    parser.add_argument("--check", action="store_true",
                        help="print the verdict and set CI outputs")
    parser.add_argument("--no-probe", action="store_true",
                        help="use the session law alone, no network call")
    parser.add_argument("--force", action="store_true",
                        help="run regardless: a deliberate manual dispatch")
    parser.add_argument("--json", action="store_true",
                        help="also print the full decision as JSON")
    parser.add_argument("--schedule", default=None,
                        help="the cron string that fired, from github.event.schedule")
    parser.add_argument("--purpose", choices=PURPOSES, default=None,
                        help="what this fire is for; overrides --schedule")
    parser.add_argument("--slot", default=None,
                        help="the scan slot label, for a manual dispatch")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("choose --check")

    purpose = args.purpose
    slot = args.slot
    if purpose is None and args.schedule:
        planned_purpose, planned_slot = plan_for(args.schedule)
        purpose, slot = planned_purpose, planned_slot
    if purpose is None:
        purpose = PURPOSE_SCAN

    decision = session_gate(probe=False if args.no_probe else None,
                            force=args.force, purpose=purpose, slot=slot)
    _emit(decision, verbose=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
