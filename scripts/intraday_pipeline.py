#!/usr/bin/env python3
"""The one scheduled intraday job: scan all KMIALL, then decide.

Rebuild 2026-10-09. This script no longer contains strategy logic. It is the
orchestrator only:

    scan  ->  src/signals/momentum_scanner.py (the ONE scanner)
          ->  src/signals/trade_state.py      (the ONE daily trade state)
          ->  owner email + Cloudflare relay  (exactly-once signal emails,
                                              the app's card, the research log)

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
  * live trading stays disabled; this script can only record paper outcomes;
  * the decision time is the time the CAPTURE can actually speak for: when the
    capture holds no bar at or before a slot, the as_of the observation carries
    is the tape's newest completed minute, not the nominal slot label
    (owner defect 2026-10-28: GitHub delivered the 11:37 cron at ~11:50, the
    tape started at ~11:50, slot label 11:30 predates its own tape by design,
    so the scan read 0/317 and called it DATA BLOCKED).
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
    KARACHI, band_bounds, close_time, current_band, is_scan_window,
    is_trading_day, now_karachi,
)
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
    """Email one notification to the owner, exactly once per (kind, day).

    Owner order 2026-10-29: the chat channel is retired and its bot is gone,
    so the relay's /notify hop is retired. Every notification now travels
    through the watched owner email issue (src/notify/owner_email.py), whose
    comment ledger keeps one email per marker no matter how often a fire
    repeats: GitHub cron runs, band loop and backstop slots land on the same
    day and the second send is refused, not duplicated. The signal branches
    do NOT call this: they email their verdicts directly with a
    signal-*:<date> marker (email_signal below), so an event never travels
    twice. `deliver` remains for the operational senders (capture alerts,
    agent rotation warnings), which dedupe on their own kind marker.

    Fail closed for the delivery record: True when the email is on the
    ledger, False when the transport refused, and the reason is named in the
    log so a failure is readable without a dashboard; no credential is ever
    part of it (SO-5).
    """
    return email_signal(text, f"{kind}:{date.today().isoformat()}")


def email_signal(text: str, marker: str) -> bool:
    """Email the owner the actual call, from Actions (owner order 2026-10-22).

    The consumer does not use a chat app any more; a notification lands as
    email through the watched owner email issue (src/notify/owner_email.py),
    whose comment ledger keeps one email per marker. The text is the exact
    body the scanner issued, never reworded, and the call is best effort for
    the verdict itself: a mail failure never changes a verdict, the card or
    the archived session record. The RETURN value is the delivery record:
    True when the email is on the ledger (a fresh send, or this exact marker
    already went out today, which for a repeated fire of the same event is a
    delivery), False when the transport failed, which the caller records as
    an undelivered notification rather than a refusal of the candidate.
    """
    from src.notify.owner_email import send

    try:
        if send(text, marker):
            print(f"owner email sent ({marker})")
        return True
    except Exception as exc:  # noqa: BLE001 - an email is best effort
        print(f"owner email failed ({marker}): {type(exc).__name__}")
        return False


def push_card(text: str, state: SessionState | None = None,
              signature: str | None = None) -> bool:
    """Write the current verdict to the app's signal card (POST /signals).

    The card must show what the scan decided TODAY. Without this the app kept
    a stale multi-day-old line, because scan verdicts only travelled to
    the retired chat hop through /notify. Best-effort: a card failure never changes a
    verdict, and the local observation file remains the record of truth.

    When a session state is supplied the push is IDEMPOTENT, and what counts
    as a change is the VERDICT, not the clock: ``signature`` is the body that
    was decided, while the dated header carries the slot the decision was
    taken in. Owner report 2026-10-19: a one second loop republished a card
    whose only difference was the header time, which spent the relay's free KV
    write quota (1,000 a day) and left the phone showing a three-day-old card
    once writes started being refused. Deduping on the verdict is what makes
    the one second cadence free; the app's once-a-second freshness comes from
    /health and the broker feed, not from a rewritten card.
    """
    key = signature if signature is not None else text
    if state is not None and not state.card_is_new(key):
        print("card verdict unchanged; not republished")
        return False
    try:
        relay_request("POST", "/signals", {"signals": text})
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"card push failed: {type(exc).__name__}")
        return False
    if state is not None:
        state.note_card(key)
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


def archive_signature(payload: dict) -> str:
    """What the observation says, without any clock field.

    The signature covers everything that could change a reader's answer:
    status, reason, the quality counts, the market context, the ranked
    candidates and the trade state. as_of and slot are excluded on purpose:
    they move on every scan by construction, so including them would make
    the signature never match and the archive would be re-POSTed every
    second again (which is exactly the quota burn this dedupe exists to
    stop: 2026-10-27 recorded only 09:52-11:31 of observations because the
    relay refused the rest of the day).
    """
    quality = payload.get("data_quality") or {}
    market = payload.get("market") or {}
    candidate = payload.get("candidate") or {}
    observed = payload.get("observed_candidate") or {}
    state = payload.get("trade_state") or {}
    essence = {
        "date": payload.get("date"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "delivered": payload.get("delivered"),
        "coverage": quality.get("coverage"),
        "with_bars": quality.get("symbols_with_bars"),
        "expected": quality.get("symbols_expected"),
        "rankables": quality.get("rankable_symbols"),
        "fresh": quality.get("fresh_coverage"),
        "market": (market.get("status"), market.get("breadth"),
                   market.get("median_return")),
        "ranked": [r.get("symbol") for r in (payload.get("ranked_top") or [])],
        "candidate": (candidate.get("symbol") or observed.get("symbol"),
                      candidate.get("score") or observed.get("score")),
        "state": (state.get("state"), state.get("trades_today"),
                  state.get("target_hit"), state.get("stop_hit")),
        "gate_tally": {k: v for k, v in
                       sorted((payload.get("gate_tally") or {}).items())},
    }
    return hashlib.sha256(
        json.dumps(essence, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def slot_email(payload: dict) -> None:
    """Email the owner the slot's full verdict, when this runner may.

    Gated on EMAIL_SLOT_VERDICTS=1, which only the scheduled Actions slots set
    (intraday-capture.yml). The one shared email channel
    (src/notify/owner_email.py) keeps exactly-once per slot through its
    comment ledger marker `slot-verdict:<day>:<HH:MM>`, so a second fire, a
    band backstop or a replay cannot double-send the same slot.
    """
    if os.environ.get("EMAIL_SLOT_VERDICTS", "").strip() != "1":
        return
    try:
        slot = relay_slot(payload.get("slot") or "10:00")
        marker = f"slot-verdict:{payload.get('date')}:{slot}"
    except ValueError:
        print(f"slot email skipped: unusable slot {payload.get('slot')!r}")
        return
    email_signal(slot_verdict_text(payload), marker)


def archive_verdict(state: SessionState, payload: dict, route: str,
                    body: dict) -> bool:
    """Archive the verdict once per DISTINCT answer, not once per scan.

    When the essence of the verdict has not changed since the last POST (same
    status, reason, counts and candidates), the archive already holds the
    answer and nothing is sent. First scan of a minute, a candidate appearing,
    coverage moving: each one is a change and is stored. The thousand-a-day
    KV writes are for new answers, not for re-stating the old one.
    """
    snapshot = body.get("snapshot") if isinstance(body, dict) else None
    signature = archive_signature(snapshot if snapshot is not None else body)
    if not state.archive_is_new(signature):
        print("research archive: verdict unchanged; not restated")
        return False
    ok = archive(route, body)
    if ok:
        state.note_archive(signature)
        state.save()
    return ok


def slot_verdict_text(payload: dict) -> str:
    """The full detail of one scan slot, exactly as the owner asked for it.

    Everything a decision rested on, in one message: the verdict, why, the
    data state, the market, the ranked candidates, and, on a NO TRADE, the
    gate rejection counts that say why nothing passed.
    """
    quality = payload.get("data_quality") or {}
    market = payload.get("market") or {}
    state = payload.get("trade_state") or {}
    delivery = payload.get("delivery") or {}
    lines = [
        f"SLOT VERDICT {payload.get('date')} {payload.get('slot')} PKT",
        "",
        f"Verdict: {payload.get('status')}",
        f"Reason: {payload.get('reason')}",
        f"KMIALL scanned: {quality.get('symbols_with_bars')}/{quality.get('symbols_expected')} "
        f"({(quality.get('coverage') or 0) * 100:.1f}% of the universe, "
        f"{quality.get('rankable_symbols')} rankable, "
        f"{quality.get('leaders_fresh', 0)}/{quality.get('leader_symbols', 0)} "
        "volume leaders fresh)",
        "",
        f"Market: {market.get('status', 'UNKNOWN')} "
        f"(breadth {(market.get('breadth') or 0):.1%}, "
        f"median {(market.get('median_return') or 0) * 100:+.2f}%)",
        "",
        f"Source: {quality.get('source', 'unknown')}. "
        f"Bars seen {quality.get('duplicate_bars')} duplicate rows on the wire, "
        f"malformed {quality.get('malformed_bars')}, "
        f"volume {'available' if quality.get('volume_available') else 'NOT available'}",
    ]
    if payload.get("ranked_top"):
        lines.append("")
        lines.append("Ranked top candidates that DID pass every gate:")
        for row in payload["ranked_top"][:8]:
            price = (row.get("price") or {})
            lines.append(
                f"  {row.get('symbol')} score {row.get('score')} "
                f"entry {price.get('last') if price else row.get('entry')} "
                f"stop {row.get('stop_loss')} target {row.get('target')} "
                f"net R/R {row.get('net_reward_risk')}")
    tally = payload.get("gate_tally") or {}
    if tally:
        lines.append("")
        lines.append("Every gate and how many symbols each one rejected:")
        lines.extend(f"  {line}" for line in scanner.gate_tally_lines(tally, limit=12))
    lines.extend([
        "",
        f"Trade state: {state.get('state')} (trades today: "
        f"{state.get('trades_today')})",
        f"Delivery: {payload.get('delivered') or 'none'} "
        f"({delivery.get('state') or 'no delivery attempt this slot'})",
    ])
    return "\n".join(lines)


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
    # ASCII only (owner report 2026-10-20). The separator used to be U+00B7 and
    # reached the relay as the two code points U+00C2 followed by U+00B7: UTF-8
    # that had already been decoded as latin-1 somewhere between this f-string
    # and the card store.
    # The header is not worth a charset argument, so it carries no non-ASCII at
    # all and the transport's decoding can no longer change what a reader sees.
    return f"{header} | {slot} PKT\n{body}"


def scheduled_as_of(slot: str, day=None) -> datetime:
    d = day or now_karachi().date()
    hm = tuple(int(part) for part in slot.split(":"))
    return datetime(d.year, d.month, d.day, hm[0], hm[1],
                    hm[2] if len(hm) == 3 else 0, tzinfo=KARACHI)


def session_legal(as_of: datetime) -> bool:
    """The scanner may only run in the MARKET state (SO-8).

    Band and state aware: the Friday midday break is not a session, and the
    owner's order of 2026-10-11 rules out the pre-market and post-market
    windows entirely, so a scheduled scan that lands in any of them is
    refused rather than run against a shut market. The law itself lives in
    src/data/sessions.py.
    """
    return is_scan_window(as_of)


def completed_through(session: scanner.SessionData, moment: datetime) -> datetime | None:
    """The newest bar the capture holds that had fully completed by `moment`.

    Bar timestamps denote minute OPEN, so a bar is complete when its minute has
    passed. Returns None when nothing completed exists.
    """
    newest: datetime | None = None
    for rows in session.bars.values():
        for bar in rows:
            stamp = bar.timestamp
            if stamp + timedelta(minutes=1) <= moment and (
                    newest is None or stamp > newest):
                newest = stamp
    return newest


def decision_time(slot: str, day: date, session: scanner.SessionData,
                  moment: datetime) -> tuple[datetime, str]:
    """The honest decision time for a scan, and where it came from.

    Normally a scan decides at its scheduled slot: that label is what makes a
    replay deterministic and a slot email idempotent. But a cron that GitHub
    delivered late may hold a capture whose first bar is AFTER that very slot,
    and scanning "as of 11:30" with a tape that starts at 11:50 reads 0/317
    and invents a data fault out of a scheduling fact. So when the capture
    holds no bar at or before the scheduled time, the decision time becomes
    the tape's newest completed minute instead, capped at the real clock. A
    replay is never touched: a full-day replay tape has bars at every slot,
    so this branch cannot fire on one.
    """
    scheduled = scheduled_as_of(slot, day)
    for rows in session.bars.values():
        for bar in rows:
            if bar.timestamp <= scheduled:
                return scheduled, "scheduled_slot"
    newest = completed_through(session, moment)
    if newest is None:
        return scheduled, "scheduled_slot"
    # Cap at the band close of the scheduled time, so a fire delivered after
    # the close cannot dress a post-market scan up as an in-band verdict; the
    # near-band-close entry gate then refuses anything entered that late.
    cap = moment
    scheduled_band = current_band(scheduled)
    if scheduled_band is not None:
        _, closes = band_bounds(day, scheduled_band)
        cap = min(cap, closes)
    return min(newest + timedelta(minutes=1), cap), "tape_newest_bar"


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


def monitor_exit(state: SessionState, session: scanner.SessionData) -> tuple | None:
    """First subsequent completed-bar exit, conservative stop-first on ties.

    Minute timestamps are opens. Do not skip the first minute starting exactly
    at entry; do skip the minute containing a mid-minute signal. A target is
    valued at its reference, not the arbitrary close of the touching bar.
    """
    if not state.in_position() or not state.entry_time:
        return None
    entered = datetime.fromisoformat(state.entry_time)
    for bar in session.bars.get(state.symbol or "", []):
        if bar.timestamp < entered or bar.timestamp + timedelta(minutes=1) > session.as_of:
            continue
        target = bar.high >= state.target_price
        if state.stop_loss is not None and bar.low <= state.stop_loss:
            price = min(bar.open, state.stop_loss)
            state.mark_stop_hit(price, bar.timestamp, ambiguous=target)
            return (state.exit_reason, price, bar.timestamp)
        if target:
            state.mark_target_hit(state.target_price, bar.timestamp)
            return ("TARGET_HIT", state.target_price, bar.timestamp)
    return None


def session_close_price(session: scanner.SessionData, symbol: str | None) -> float | None:
    """Value only the actual last session minute, never another stock's freshness."""
    hour, minute = close_time(session.day)
    closed = datetime(session.day.year, session.day.month, session.day.day,
                      hour, minute, tzinfo=KARACHI)
    if session.as_of < closed:
        return None
    rows = session.bars.get(symbol or "", [])
    final = next((bar for bar in reversed(rows)
                  if bar.timestamp == closed - timedelta(minutes=1)), None)
    return final.close if final is not None else None


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

    # The cheap gate stays cheap: an as_of the law already refuses never
    # parses the capture at all.
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

    # The tape first, the decision time second: a fire GitHub delivered late
    # must decide from the tape it actually banked (owner defect 2026-10-28).
    # The normal path is byte-for-byte the old one: load at the scheduled
    # minute, scan it. Only when THAT load holds no bar at all - the tape's
    # first print is after the very slot the label names - does the late-fire
    # branch reload at the real clock and take the honest minute instead.
    session = scanner.load_session(path, symbols, as_of)
    as_of_basis = "scheduled_slot"
    if not any(session.bars.values()):
        moment = now_karachi()
        session = scanner.load_session(path, symbols, moment)
        as_of, as_of_basis = decision_time(slot, day, session, moment)
        session.as_of = as_of
        print(f"late fire: deciding at {as_of:%H:%M} PKT from the tape actually "
              f"held ({as_of_basis}); scheduled slot {slot} predates this tape")
    quality = scanner.assess_quality(session, symbols)

    if quality.status == scanner.DATA_BLOCKED:
        state.block(quality.reason, coverage=quality.coverage,
                    scanned=quality.symbols_with_bars,
                    expected=quality.symbols_expected)
        state.save()
        text = scanner.scan_blocked_message(quality)
        payload = {
            "date": day.isoformat(), "slot": slot, "as_of": as_of.isoformat(),
            "as_of_basis": as_of_basis,
            "status": scanner.DATA_BLOCKED, "reason": quality.reason,
            "capture": capture_label(path, session),
            "data_quality": quality.as_dict(), "trade_state": state.to_dict(),
            "ai": {"active": False, "reason": "Kalman flip rules have no daily-model routing"},
            "universe_size": len(symbols),
            "universe_sha256": universe_fingerprint(symbols),
            "scanner_version": config.SCANNER_VERSION,
            "config": config.config_snapshot(),
        }
        write_observation(payload)
        # Owner order 2026-10-15: the scan cadence is background. A blocked
        # scan is a data state, not a market event, so it updates the card and
        # the archived observations WITHOUT a chat op text every 30
        # seconds. Only ever a signal travels.
        push_card(card_text(day, slot, text, alert=False), state, signature=f"{day}|{text}")
        # Deduped on the verdict essence: an unchanged data state is not
        # re-written into the relay's KV every cycle (the 2026-10-27 quota
        # burn). A change in coverage, newest bar or reason is a change.
        archive_verdict(state, payload, "/research/observation",
                        {"date": day.isoformat(), "slot": slot,
                         "snapshot": payload})
        # Owner order 2026-10-28: email the slot's full verdict on schedule.
        slot_email(payload)
        print(json.dumps(payload, indent=2, allow_nan=False))
        return payload

    ai_status = {"active": False, "reason": "Kalman flip rules have no daily-model routing"}
    result = scanner.select_one(session, quality)
    context = result.market

    if state.in_position():
        exit_event = monitor_exit(state, session)
        if exit_event is not None:
            _, price, stamp = exit_event
            state.save()
            text = (scanner.target_hit_message(state.symbol or "", state.entry_price or 0.0,
                                               state.target_price or 0.0, price, stamp)
                    if state.target_hit else
                    f"STOP HIT\nSymbol: {state.symbol}\nExit reference: {price:.4f}\n"
                    f"Stop Loss: {state.stop_loss:.4f}\nDaily lock remains engaged.")
            accepted = email_signal(text, f"signal-exit:{day.isoformat()}")
            delivery = {"channel": "owner-email", "kind": "signal-exit",
                        "ok": accepted,
                        "state": ("delivered" if accepted
                                  else "refused_by_owner_email")}
            push_card(card_text(day, slot, text, alert=True), state, signature=f"{day}|{text}")
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
            push_card(card_text(day, slot, reason, alert=False), state, signature=f"{day}|{reason}")
            print(reason)
        else:
            entry = result.candidate["price"]["last"]
            state.note_candidate(result.candidate["symbol"], result.candidate["score"])
            state.enter(result.candidate["symbol"], entry, as_of, result.candidate["score"],
                        stop_loss=result.candidate.get("stop_loss"))
            state.save()
            text = scanner.signal_message(result.candidate, context, entry, as_of)
            sent = email_signal(text, f"signal-buy:{day.isoformat()}")
            push_card(card_text(day, slot, text, alert=True), state, signature=f"{day}|{text}")
            delivery = {"channel": "owner-email", "kind": "signal-buy",
                        "ok": sent,
                        "state": ("delivered" if sent
                                  else "refused_by_owner_email")}
            # A candidate the owner never received is NEVER reported as a delivered
            # trade. The trade itself still stands in the session state (the paper
            # position is real and is valued at the close either way); what is
            # corrected here is the claim that the owner was told about it.
            delivered = "TRADE" if sent else "TRADE_UNDELIVERED"
            entered = result.candidate
            status = result.status
            reason = result.reason
            if not sent:
                reason = (f"{reason}; the signal was entered and the owner email "
                          f"did NOT confirm the delivery")
                state.last_reason = reason
                state.save()
    elif result.status == scanner.CALL_WATCH and not state.trade_taken:
        # Owner order 2026-10-29: a scan whose rank table is non-empty is
        # DELIVERED end-to-end even when the market veto kept it from being
        # a paper entry. The watch is NOT a trade: no paper position opens,
        # no ONE TRADE claim is taken, and a later fully confirmed entry can
        # still open the same day. What is delivered is the ranked top with
        # its measured setup and the veto that explains why it is a watch.
        status = result.status
        reason = result.reason
        watch_text = scanner.call_watch_message(result, quality, context,
                                                as_of)
        sent = email_signal(watch_text, f"signal-callwatch:{day.isoformat()}")
        delivery = {"channel": "owner-email", "kind": "signal-callwatch",
                    "ok": sent,
                    "state": ("delivered" if sent
                              else "refused_by_owner_email")}
        push_card(card_text(day, slot, watch_text, alert=True), state,
                  signature=f"{day}|{watch_text}")
        state.last_reason = f"call watch delivered instead of entry: {reason}"
        state.save()
        delivered = "CALL_WATCH" if sent else "CALL_WATCH_UNDELIVERED"
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
                     f"{state.entry_price}, target {state.target_price}, "
                     f"stop loss {state.stop_loss}. "
                     f"{state.last_reason or 'position being monitored'}.")
        push_card(card_text(day, slot, card_body, alert=state.target_hit), state, signature=f"{day}|{card_body}")
    else:
        status = result.status
        reason = result.reason
        if result.status == scanner.NO_TRADE:
            state.no_trade(result.reason, coverage=quality.coverage,
                           scanned=quality.symbols_with_bars,
                           expected=quality.symbols_expected)
            state.save()
            no_trade_text = scanner.no_trade_message(quality, context,
                                                     result.gate_tally)
            # Owner order 2026-10-15: a market NO TRADE is not a signal. The
            # verdict is written, archived and carded, never messaged.
            push_card(card_text(day, slot, no_trade_text, alert=False), state, signature=f"{day}|{no_trade_text}")
            delivered = "NO_TRADE"

    payload = {
        "date": day.isoformat(),
        "slot": slot,
        "as_of": as_of.isoformat(),
        "as_of_basis": as_of_basis,
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
        "ranked_top": [{k: row.get(k) for k in ("symbol", "score", "strategy",
                                                "setup", "stop_loss", "target",
                                                "net_reward_risk")}
                       for row in result.ranked],
        "gate_tally": {k: v for k, v in
                       sorted(result.gate_tally.items())} if result else {},
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
    # Deduped on the verdict essence: re-stating an unchanged NO TRADE burns
    # the relay's KV quota without adding a word (2026-10-27 archive stop).
    archive_verdict(state, payload, "/research/observation",
                    {"date": day.isoformat(), "slot": slot,
                     "snapshot": payload})
    # Owner order 2026-10-28: email the slot's full verdict on schedule.
    slot_email(payload)
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
    monitor_exit(state, session)
    if state.stop_hit:
        outcome_label = state.exit_reason
        gross_return = state.return_pct
    elif state.target_hit:
        outcome_label = "TARGET_HIT"
        gross_return = state.return_pct
    elif state.entry_price and quality.status == scanner.DATA_BLOCKED:
        # An open paper position that cannot be valued from real bars is never
        # given a made-up return. It is labelled UNVERIFIABLE instead.
        outcome_label = "UNVERIFIABLE"
    elif state.entry_price:
        final = session_close_price(session, state.symbol)
        if final is not None:
            gross_return = round(final / state.entry_price - 1.0, 6)
            outcome_label = "CLOSED_AT_SESSION_END"
        else:
            outcome_label = "UNVERIFIABLE"
    if state.entry_time and gross_return is not None:
        end_at = datetime.fromisoformat(state.exit_time) if state.exit_time else as_of
        minutes_held = int((end_at - datetime.fromisoformat(state.entry_time))
                           .total_seconds() // 60)
    # Net is gross minus the modelled round trip and CGT on a positive result,
    # using the ONE cost schedule in src/config.py (the same numbers the frozen
    # research gate labels with, so a paper outcome and a research label agree).
    net_return = config.net_return(gross_return)
    if state.entry_price:
        state.close_day(session_close_price(session, state.symbol)
                        if outcome_label == "CLOSED_AT_SESSION_END" else None, as_of)
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
    parser = argparse.ArgumentParser(description="KMIALL long-only Kalman Trend scan")
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
