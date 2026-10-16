#!/usr/bin/env python3
"""The one scheduled intraday job: scan all KMIALL, then decide.

Rebuild 2026-10-09. This script no longer contains strategy logic. It is the
orchestrator only:

    scan  ->  src/signals/momentum_scanner.py (the ONE scanner)
          ->  src/signals/trade_state.py      (the ONE daily trade state)
          ->  Cloudflare relay                (signals, notify, research log)

Modes:

    --scan --slot HH:MM   one in-session pass: capture, validate coverage,
                          rank every eligible KMIALL symbol, enter at most one
                          paper trade, monitor the +2% target
    --finalize            post-close pass: value the paper position, write the
                          session record, lock the day, update the paper gate

Honesty rules enforced here:

  * the scanner never runs outside the configured Karachi session (SO-8);
  * a data failure is reported as SCAN BLOCKED with measured coverage and
    never as a market NO TRADE;
  * one trade per market day, persisted on disk, so a restart cannot reset it;
  * live trading stays disabled; this script can only record paper outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import eligibility  # noqa: E402
from src.data import tape_bars  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI, close_time, is_scan_window, is_trading_day, now_karachi,
)
from src.signals import ai_model  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import trade_state  # noqa: E402
from src.signals.trade_state import SessionState, State  # noqa: E402
from src.research import session_history  # noqa: E402
from src.research.forward_validation import evaluate_gate  # noqa: E402

UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
DATA_DIR = ROOT / "data" / "feed_capture"
RELAY_DEFAULT = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def forward_dir() -> Path:
    """The ONE forward-state directory.

    Derived from ``trade_state.ROOT`` at CALL time, never frozen at import, so
    the daily state machine and every file this orchestrator writes share a
    single root. That is what lets a test redirect the whole forward-state
    surface by patching one attribute, and it is why an offline test run can
    never overwrite the owner's real session records (observation, outcome and
    gate are read as evidence of what actually happened on the market).
    """
    return trade_state.ROOT / "data" / "forward"


def load_kmiall(path: Path = UNIVERSE_FILE) -> list[str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    symbols = sorted({
        str(row["symbol"]).strip().upper()
        for row in rows
        if row.get("isShariahCompliant") is True
        and "KMIALLSHR" in row.get("listedIn", [])
        and row.get("symbol")
    })
    # ETFs are NEVER scanned (owner order 2026-10-15): basket instruments are
    # not made for intraday trading, and they would otherwise ride the index
    # instead of its own momentum. Since 2026-10-16 the exclusion comes from
    # the one eligibility service rather than a name test written here, and it
    # is logged with its size, so a universe file that still lists an ETF is
    # not silently mis-shaped and a symbol the service cannot classify is
    # refused rather than admitted (fail closed).
    screened = eligibility.screen(symbols, universe=symbols)
    if config.EXCLUDE_ETFS and screened.excluded:
        print(f"ETF exclusion (owner order 2026-10-15): not scanning "
              f"{', '.join(sorted(row.symbol for row in screened.excluded))}")
    if screened.unknown:
        print(f"eligibility: refusing {len(screened.unknown)} symbol(s) whose "
              f"classification could not be settled: "
              f"{', '.join(sorted(row.symbol for row in screened.unknown))}")
    symbols = screened.eligible
    if not symbols:
        raise RuntimeError("KMIALL/Shariah universe resolved to zero symbols")
    return symbols


def universe_fingerprint(symbols: list[str]) -> str:
    payload = "\n".join(sorted(set(symbols))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def relay_url() -> str:
    """The relay's URL, through the one resolver the notification path uses.

    RELAY_URL, then ``data/relay_url.txt`` (both via
    src/notify/schedule_runner.load_relay_url), then the known default. Every
    workflow passes the variable and a fresh runner has no file, so the
    default stays as the last resort; what changed on 2026-10-16 is that the
    file is now consulted at all, which is what the PC needs.
    """
    from src.notify.schedule_runner import load_relay_url

    try:
        return load_relay_url()
    except RuntimeError:
        return RELAY_DEFAULT


def admin_token() -> str:
    """RELAY_ADMIN_TOKEN from the environment, then the gitignored repo .env.

    Owner defect found 2026-10-16. This read ``os.environ`` only. A scan
    started by the local tick has no wrapper to export it, so on this PC a
    genuine candidate was entered into the session state (FCCL, 2026-10-13
    11:30) and then dropped at the delivery step, with only "delivery failed
    (signals): RuntimeError" in the log, while ``.env`` held exactly the token
    every other module resolves (market_snapshot, signal_push and
    schedule_runner all read it). One resolver for the whole path.

    The token is never printed, logged or embedded in an exception (SO-5).
    """
    from src.notify.schedule_runner import load_relay_admin_token

    return load_relay_admin_token()


def relay_request(method: str, route: str, payload: dict | None = None):
    response = requests.request(
        method, relay_url() + route, json=payload,
        headers={"x-admin-token": admin_token()},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"relay refused {route}: {result.get('error', 'unknown error')}")
    return result


def deliver(text: str, kind: str) -> bool:
    """Hand one message to the relay. True ONLY when it accepted it.

    Acceptance is not delivery, and the two are kept apart on purpose. The
    relay answers as soon as it has taken the message and sends it to Telegram
    in the background (measured 2026-10-16: Telegram took 42.2 seconds to
    answer, far past any sender's budget), so Telegram's own outcome is
    recorded at the relay and reported by /status as ``last_delivery`` rather
    than guessed here. What this function still refuses to do is call a
    refusal a delivery: the caller used to discard this return value and
    record ``delivered: TRADE`` either way.

    The reason is named in the log so the cause is readable without a
    dashboard; no credential is ever part of it (SO-5).
    """
    try:
        relay_request("POST", "/notify", {"text": text, "kind": kind})
        return True
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"delivery failed ({kind}): {type(exc).__name__}: {exc}")
        return False


def push_card(text: str, state: SessionState | None = None) -> bool:
    """Write the current verdict to the app's signal card (POST /signals).

    The card must show what the scan decided TODAY. Without this the app kept
    a stale multi-day-old line, because scan verdicts only travelled to
    Telegram through /notify. Best-effort: a card failure never changes a
    verdict, and the local observation file remains the record of truth.

    When a session state is supplied the push is IDEMPOTENT: a tick that
    reaches the same verdict as the previous tick does not republish it. That
    is what makes a 4-minute local runner safe to fire all session without
    filling the card with identical lines.
    """
    if state is not None and not state.card_is_new(text):
        print("card verdict unchanged; not republished")
        return False
    try:
        relay_request("POST", "/signals", {"signals": text})
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"card push failed: {type(exc).__name__}")
        return False
    if state is not None:
        state.note_card(text)
        state.save()
    return True


def relay_slot(slot: str) -> str:
    """The slot label the relay's research routes accept: HH:MM.

    src/data/scan_schedule.py labels a 30 second cadence with seconds
    (11:34:00, 11:34:30) so the once-per-slot guard sees both fires, but the
    relay's /research/observation and /research/claim validate the slot as
    HH:MM. That mismatch was silent and expensive: from the 2026-10-14 cadence
    change (SO-13) every observation POST answered 400 "invalid observation",
    so the two year research archive held nothing while the local observation
    file kept being written. Measured 2026-10-16: GET /research/observations
    returned 0 rows for 2026-10-13, 2026-10-15 and 2026-10-16 and 1 row for
    2026-10-14, the last day whose slots were minute precision.

    Normalising here, at the one boundary that speaks to the relay, keeps one
    rule: the guard keeps its seconds, the archive gets the minute it belongs
    to. Both 30 second slots inside a minute therefore name the same archive
    key, and the route's own immutability keeps the first of them, which is
    the honest record either way.
    """
    parts = str(slot).split(":")
    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(f"unusable scan slot: {slot!r}")
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


def archive(route: str, payload: dict) -> bool:
    """Best-effort write to the relay's durable research archive.

    Observations, daily outcomes and the production gate are stored in KV for
    two years (SO: research retention), so the record survives even though the
    GitHub Actions artifacts expire after 90 days. A failure is reported, never
    hidden: the caller records the honest storage status either way, and the
    relay's own words for the refusal are printed (SO-5: the relay's error
    strings carry no credential).
    """
    body = payload
    if "slot" in body:
        body = {**body, "slot": relay_slot(body["slot"])}
    try:
        relay_request("POST", route, body)
        return True
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"research archive {route} failed: {type(exc).__name__}: {exc}")
        return False


def claim_signal(day, slot: str) -> tuple[bool, str]:
    """Take the day's one signal claim from the relay. The authoritative lock.

    The local session file (src/signals/trade_state.py) is a per-machine lock:
    it cannot see another runner, and the cloud runs a band loop plus scheduled
    backstop slots, each starting from a restored copy of the day's state. Two
    runs that restore the same pre-trade state can both decide to enter, which
    is exactly how the same Karachi day would emit two accepted BUY candidates.
    The relay's /research/claim is the one shared place that can answer "has
    today's signal already been claimed" across machines, and until now nothing
    called it.

    Returns (claimed, detail). Fails CLOSED: a relay that cannot answer means
    no entry, because an unverifiable lock cannot promise the one-trade rule
    (SO-3: the honest outcome is a refusal that says why).
    """
    if not config.SIGNAL_CLAIM_REQUIRED:
        return True, "claim not required by config"
    try:
        answer = relay_request("POST", "/research/claim",
                              {"date": day.isoformat(),
                               "slot": relay_slot(slot)})
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        return False, (f"the day's signal claim could not be taken "
                       f"({type(exc).__name__}): no entry without it")
    if answer.get("claimed"):
        return True, "claimed"
    return False, ("today's one signal was already claimed by another "
                   "runner; no further entry is possible")


def card_text(day, slot: str, body: str, alert: bool) -> str:
    """Dated card header so the app never shows an undated verdict, and a
    trade alert carries the INTRADAY ALERT marker the daily push looks for
    before it overwrites an intraday card (src/signals/signal_push.py)."""
    header = (f"INTRADAY ALERT {day.isoformat()}" if alert
              else f"QoR intraday {day.isoformat()}")
    return f"{header} \u00b7 {slot} PKT\n{body}"


def scheduled_as_of(slot: str, day=None) -> datetime:
    d = day or now_karachi().date()
    hm = tuple(int(part) for part in slot.split(":"))
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=KARACHI)


def session_legal(as_of: datetime) -> bool:
    """The scanner may only run in the MARKET state (SO-8).

    Band and state aware: the Friday midday break is not a session, and the
    owner's order of 2026-10-11 rules out the pre-market and post-market
    windows entirely, so a scheduled scan that lands in any of them is
    refused rather than run against a shut market. The law itself lives in
    src/data/sessions.py.
    """
    return is_scan_window(as_of)


def capture_path(day) -> Path:
    """The eClear OHLC servlet capture. The secondary source now.

    Kept because a capture already on disk is still genuine data and the
    loader for it is untouched; the servlet itself serves no bars, so the tape
    below is what a live scan reads (owner order 2026-10-14).
    """
    return DATA_DIR / f"ohlc_{day:%Y%m%d}.ndjson"


def tape_capture_path(day) -> Path:
    """The broker MKT-FEED tape capture: the bar source (SO-3, 2026-10-14)."""
    return tape_bars.capture_path(day)


def resolve_capture(day) -> Path:
    """Which capture a scan should read, and why it is that one.

    The tape comes first because it is the source that is genuinely alive: the
    system subscribes to it every session, and it is what the phone's card and
    the buy/sell split already read. The servlet capture is used when no tape
    exists for the day at all, so a machine that has an older capture on disk
    still scans off it instead of reporting an empty market. When neither
    exists the tape path is returned, and the loader reports the missing file
    as the DATA failure it is rather than inventing a capture.
    """
    tape = tape_capture_path(day)
    if tape.is_file() and tape.stat().st_size > 0:
        return tape
    poller = capture_path(day)
    if poller.is_file() and poller.stat().st_size > 0:
        print(f"no tape capture for {day.isoformat()}; reading the servlet "
              f"capture {poller.name} instead")
        return poller
    return tape


def target_check(state: SessionState, session: scanner.SessionData):
    """Was the +2% target touched by any bar after the recorded entry?"""
    if not state.in_position() or state.entry_time is None:
        return None
    entry_at = datetime.fromisoformat(state.entry_time)
    rows = session.bars.get(state.symbol or "", [])
    for bar in rows:
        if bar.timestamp <= entry_at:
            continue
        if bar.high >= state.target_price:
            return bar
    return None


def last_price(session: scanner.SessionData, symbol: str | None) -> float | None:
    rows = session.bars.get(symbol or "")
    return rows[-1].close if rows else None


def capture_label(path: Path, session: scanner.SessionData) -> dict:
    """Which capture spoke, in what format, and what it could not see.

    Every observation and session record carries this, so a reader of the
    archive can tell a tape-based scan from a servlet-based one without
    reading the file name, and can see the source's own notes about the holes
    and the carried minutes (SO-3).
    """
    return {
        "path": str(path),
        "file": path.name,
        "format": scanner.detect_capture_format(path),
        "exists": path.is_file(),
        "bars_seen": session.bars_seen,
        "bars_rejected": session.bars_rejected,
        "duplicate_rows": session.duplicate_bars,
        "source": session.source,
        "notes": list(session.notes),
    }


def write_observation(payload: dict) -> Path:
    target = forward_dir()
    target.mkdir(parents=True, exist_ok=True)
    out = target / "observation.json"
    out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    return out


def ai_component() -> tuple[dict, dict[str, float] | None]:
    """The trained AI prior and an honest status, both best effort.

    A missing artifact, an ineligible model or an unreadable panel disables the
    prior and is REPORTED; it never blocks the rule scan, because the rule
    scanner is the strategy and the prior is a second opinion on it.
    """
    status = ai_model.status()
    prior = None
    if status.get("active"):
        try:
            prior = ai_model.live_probabilities()
            # Record WHICH session's features produced the prior. A probability
            # computed from a stale daily panel is still a probability, but the
            # observation must say so rather than imply it is yesterday's setup.
            cache_path = ai_model.live_feature_cache()
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                status = {**status,
                          "prior_panel_as_of": cached.get("panel_as_of"),
                          "prior_symbols": len(cached.get("probabilities") or {})}
        except Exception as exc:  # noqa: BLE001 - reported, never invented
            status = {**status, "active": False,
                      "reason": f"prior unavailable: {type(exc).__name__}"}
    return status, prior


def run_scan(slot: str, capture: Path | None = None,
             day: date | None = None) -> dict:
    """One scheduled scan against a session capture.

    `day` is the replayed session's day (scripts/replay_audit.py passes one);
    a live caller never sets it, and the clock stays the one law (SO-8).
    """
    day = day or now_karachi().date()
    as_of = scheduled_as_of(slot, day)
    symbols = load_kmiall()
    path = capture or resolve_capture(day)

    if not session_legal(as_of):
        print(f"{as_of:%Y-%m-%d %H:%M} PKT is outside the Karachi session: "
              f"the scanner does not run")
        return {"status": "OUTSIDE_SESSION", "slot": slot}

    state = SessionState.load(day)
    state.begin_session()
    state.begin_scan()

    # Whether a notification was actually accepted, and by what. None means
    # no message was owed on this scan; a dict means one was attempted, and
    # ``ok`` is the relay's own answer, never assumed.
    delivery: dict | None = None
    # And the day's signal claim, when one was asked for: the shared lock's
    # answer belongs in the record beside the delivery, not only in the log.
    claim_record: dict | None = None

    session = scanner.load_session(path, symbols, as_of)
    quality = scanner.assess_quality(session, symbols)

    if quality.status == scanner.DATA_BLOCKED:
        state.block(quality.reason, coverage=quality.coverage,
                    scanned=quality.symbols_with_bars,
                    expected=quality.symbols_expected)
        state.save()
        text = scanner.scan_blocked_message(quality)
        payload = {
            "date": day.isoformat(), "slot": slot, "as_of": as_of.isoformat(),
            "status": scanner.DATA_BLOCKED, "reason": quality.reason,
            "capture": capture_label(path, session),
            "data_quality": quality.as_dict(), "trade_state": state.to_dict(),
            "ai": ai_model.status(),
            "universe_size": len(symbols),
            "universe_sha256": universe_fingerprint(symbols),
            "scanner_version": config.SCANNER_VERSION,
            "config": config.config_snapshot(),
        }
        write_observation(payload)
        # Owner order 2026-10-15: the scan cadence is background. A blocked
        # scan is a data state, not a market event, so it updates the card and
        # the archived observations WITHOUT a Telegram op text every 30
        # seconds. Only ever a signal travels.
        push_card(card_text(day, slot, text, alert=False), state)
        archive("/research/observation",
                {"date": day.isoformat(), "slot": slot, "snapshot": payload})
        print(json.dumps(payload, indent=2, allow_nan=False))
        return payload

    ai_status, ai_prior = ai_component()
    result = scanner.select_one(session, quality, ai_prior, ai_status)
    context = result.market

    if state.in_position():
        hit = target_check(state, session)
        if hit is not None:
            state.mark_target_hit(hit.close, hit.timestamp)
            state.save()
            text = scanner.target_hit_message(state.symbol or "", state.entry_price or 0.0,
                                              state.target_price or 0.0, hit.close,
                                              hit.timestamp)
            accepted = deliver(text, "signals")
            delivery = {"channel": "relay:/notify", "kind": "signals",
                        "ok": accepted,
                        "state": ("relay_accepted" if accepted
                                  else "refused_by_relay")}
            push_card(card_text(day, slot, text, alert=True), state)
            print(text)
        else:
            state.last_reason = "position open, monitoring the target"
        state.save()

    delivered = None
    entered = None
    observed = result.candidate
    if result.status == scanner.TRADE and state.can_enter():
        # The shared, cross-runner lock first: the local state file cannot see
        # another runner, and the cloud runs a band loop plus backstop slots.
        claimed, claim_note = claim_signal(day, slot)
        claim_record = {"channel": "relay:/research/claim", "ok": claimed,
                        "detail": claim_note}
        if not claimed:
            status = State.DAILY_LOCKED
            reason = (f"{claim_note}; the observed candidate "
                      f"{result.candidate['symbol']} was refused")
            state.last_reason = reason
            state.save()
            delivered = "LOCKED"
            push_card(card_text(day, slot, reason, alert=False), state)
            print(reason)
        else:
            entry = result.candidate["price"]["last"]
            state.note_candidate(result.candidate["symbol"], result.candidate["score"])
            state.enter(result.candidate["symbol"], entry, as_of, result.candidate["score"])
            state.save()
            text = scanner.signal_message(result.candidate, context, entry, as_of)
            sent = deliver(text, "signals")
            push_card(card_text(day, slot, text, alert=True), state)
            delivery = {"channel": "relay:/notify", "kind": "signals",
                        "ok": sent,
                        "state": ("relay_accepted" if sent
                                  else "refused_by_relay")}
            # A candidate that the relay refused is NEVER reported as a delivered
            # trade. The trade itself still stands in the session state (the paper
            # position is real and is valued at the close either way); what is
            # corrected here is the claim that the owner was told about it.
            delivered = "TRADE" if sent else "TRADE_UNDELIVERED"
            entered = result.candidate
            status = result.status
            reason = result.reason
            if not sent:
                reason = (f"{reason}; the signal was entered and the relay did NOT "
                          f"accept the notification")
                state.last_reason = reason
                state.save()
    elif state.trade_taken:
        # The day already has its one trade. A taken trade is NEVER reported as
        # NO TRADE, and a second candidate is never presented as actionable.
        status = (State.TARGET_MONITORING if state.in_position()
                  else State.DAILY_LOCKED)
        reason = "one trade already taken today; no further entry is possible"
        if observed is not None:
            reason += "; a fresh candidate was observed and refused"
            state.last_reason = reason
            state.save()
        delivered = "LOCKED"
        card_body = (f"One trade already taken today: {state.symbol} entered at "
                     f"{state.entry_price}, target {state.target_price}. "
                     f"{state.last_reason or 'position being monitored'}.")
        push_card(card_text(day, slot, card_body, alert=state.target_hit), state)
    else:
        status = result.status
        reason = result.reason
        if result.status == scanner.NO_TRADE:
            state.no_trade(result.reason, coverage=quality.coverage,
                           scanned=quality.symbols_with_bars,
                           expected=quality.symbols_expected)
            state.save()
            no_trade_text = scanner.no_trade_message(quality, context)
            # Owner order 2026-10-15: a market NO TRADE is not a signal. The
            # verdict is written, archived and carded, never messaged.
            push_card(card_text(day, slot, no_trade_text, alert=False), state)
            delivered = "NO_TRADE"

    payload = {
        "date": day.isoformat(),
        "slot": slot,
        "as_of": as_of.isoformat(),
        "status": status,
        "reason": reason,
        "delivered": delivered,
        "delivery": delivery,
        "claim": claim_record,
        "capture": capture_label(path, session),
        "data_quality": quality.as_dict(),
        "market": context,
        "candidate": entered,
        "observed_candidate": None if entered else observed,
        "ranked_top": [{k: row.get(k) for k in ("symbol", "score", "momentum",
                                                "acceleration_label",
                                                "volume_label",
                                                "ai_probability",
                                                "ai_percentile")}
                       for row in result.ranked],
        "eligible_count": len(result.ranked),
        "coverage_text": result.coverage_text,
        "trade_state": state.to_dict(),
        "ai": ai_status,
        "universe_size": len(symbols),
        "universe_sha256": universe_fingerprint(symbols),
        "scanner_version": config.SCANNER_VERSION,
        "config": config.config_snapshot(),
    }
    write_observation(payload)
    archive("/research/observation",
            {"date": day.isoformat(), "slot": slot, "snapshot": payload})
    print(json.dumps(payload, indent=2, allow_nan=False))
    return payload


def run_finalize(capture: Path | None = None) -> dict:
    day = now_karachi().date()
    if not is_trading_day(day):
        raise RuntimeError("finalization requested on a non-trading day")
    close_h, close_m = close_time(day)
    as_of = datetime(day.year, day.month, day.day, close_h, close_m,
                     tzinfo=KARACHI) + timedelta(minutes=1)
    symbols = load_kmiall()
    path = capture or resolve_capture(day)

    state = SessionState.load(day)
    session = scanner.load_session(path, symbols, as_of)
    quality = scanner.assess_quality(session, symbols)
    context = scanner.market_context(session) if session.bars else {}

    outcome_label = "NO_CANDIDATE"
    gross_return = net_return = None
    minutes_held = None
    hit_bar = target_check(state, session)
    if hit_bar is not None and not state.target_hit:
        state.mark_target_hit(hit_bar.close, hit_bar.timestamp)
    if state.target_hit:
        outcome_label = "TARGET_HIT"
        gross_return = round(config.TARGET_PCT, 6)
    elif state.entry_price and quality.status == scanner.DATA_BLOCKED:
        # An open paper position that cannot be valued from real bars is never
        # given a made-up return. It is labelled UNVERIFIABLE instead.
        outcome_label = "UNVERIFIABLE"
    elif state.entry_price:
        final = last_price(session, state.symbol)
        if final is not None:
            gross_return = round(final / state.entry_price - 1.0, 6)
            outcome_label = "CLOSED_AT_SESSION_END"
    if state.entry_time and gross_return is not None:
        end_at = datetime.fromisoformat(state.exit_time) if state.exit_time else as_of
        minutes_held = int((end_at - datetime.fromisoformat(state.entry_time))
                           .total_seconds() // 60)
    # Net is gross minus the modelled round trip and CGT on a positive result,
    # using the ONE cost schedule in src/config.py (the same numbers the frozen
    # research gate labels with, so a paper outcome and a research label agree).
    net_return = config.net_return(gross_return)
    if state.entry_price:
        state.close_day(None if state.target_hit else last_price(session, state.symbol), as_of)
    else:
        state.close_day(None, as_of)

    record = {
        **state.session_record(),
        "gross_return": gross_return,
        "net_return": net_return,
        "cost_model": {
            "cost_side_bps": config.COST_SIDE_BPS,
            "slippage_side_bps": config.SLIPPAGE_SIDE_BPS,
            "cgt_rate": config.CGT_RATE,
        },
        "minutes_held": minutes_held,
        "outcome": outcome_label,
        "market": context,
        "capture": capture_label(path, session),
        "data_quality": quality.as_dict(),
        # The owner's own three confirmations for THIS run. The band workflows
        # already pass them; until 2026-10-16 nothing read them, so the gate's
        # production_data_ready check had no input and could only be false.
        "data_confirmations": config.data_confirmations(),
        "universe_size": len(symbols),
        "universe_sha256": universe_fingerprint(symbols),
        "scanner_version": config.SCANNER_VERSION,
    }
    state.append_journal(record)
    state.save()

    outcome = {
        "date": day.isoformat(),
        "scanner_version": config.SCANNER_VERSION,
        "outcomes_by_rule": {config.SCANNER_VERSION: record},
        "data_quality": quality.as_dict(),
    }
    # Owner defect found 2026-10-16: this was evaluate_gate([]). The gate was
    # asked to score an empty list on every finalize, so sessions_collected
    # stayed 0 for ever and live_signal_enabled could never become true no
    # matter how many sessions the system observed. It is now handed the
    # evidence the pipeline has been collecting all along: today's record, the
    # local forward state, and the relay's two-year research archive. Blocked
    # or unreadable sessions are labelled unverified by the loader and the
    # gate's own _valid_rows refuses to spend a research session on them, so
    # feeding it more rows cannot buy progress a session did not earn.
    evidence: dict = {}
    gate = evaluate_gate(session_history.session_rows(extra=[record],
                                                      report=evidence))
    gate = {**gate, "scanner_version": config.SCANNER_VERSION,
            "evidence": evidence}

    # Durable archive first (two year KV retention on the relay), then the
    # honest storage status is written into the local record. The GitHub
    # Actions artifact expires after 90 days, so this is the long lived copy.
    outcome_ok = archive("/research/outcome",
                         {"date": day.isoformat(), "sessions": [record]})
    gate_ok = archive("/research/gate", gate)
    storage = "relay+local" if (outcome_ok and gate_ok) else "local-only"
    outcome["storage_status"] = storage
    gate["storage_status"] = storage

    target = forward_dir()
    target.mkdir(parents=True, exist_ok=True)
    (target / "daily_outcome.json").write_text(
        json.dumps(outcome, indent=2, allow_nan=False), encoding="utf-8")
    (target / "production_gate.json").write_text(
        json.dumps(gate, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"outcome": outcome, "gate": gate}, indent=2, allow_nan=False))
    return {"outcome": outcome, "gate": gate}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KMIALL momentum + volume scan")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    parser.add_argument("--slot", choices=("10:00", "11:30", "13:00", "14:30", "16:00"))
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args(argv)

    if args.scan and not args.slot:
        parser.error("--scan requires --slot")
    if args.finalize:
        run_finalize(args.capture)
    else:
        run_scan(args.slot, args.capture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
