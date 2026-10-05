"""
The Sentinel - cloud intraday runner (one pass per invocation).

WHAT this is: the live bot's decision cycle, executed on GitHub Actions
instead of the owner's PC. Each workflow run performs ONE pass:

  1. poll the PSX Terminal feed once (same parser as the collector)
  2. store the snapshot (same format as the collector - archives keep
     growing without any local process)
  3. check open positions against the fresh prices (fast exit guard)
  4. if the book still has an entry slot, run the full decide cycle
     (same engine, same config, same gates as the local bot)

The workflow schedules this every ~15 minutes during PSX hours
(see .github/workflows/cloud-intraday.yml). A session costs
~24 runs x ~2 min = ~50 free-tier minutes/day. The owner's PC carries
zero of it - 2026-09-15: the local stack was holding 1.1 GB of RAM and
~4% CPU, for the last time.

State (portfolio.json, snapshots, baselines, decisions) is committed
back to the repo at the end of every pass, so the next run inherits
the book exactly where the last one left it. That commit is also how
the owner reads the day: logs/decisions.jsonl in the browser.

Signals are DELIVERED by commits (and the SIGNALS.md page); they are
not placed as orders. The owner trades manually, as always.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psx_core.paths as paths  # noqa: E402
import psx_core.sessions as sessions  # noqa: E402
import psx_core.storage as storage  # noqa: E402


def _print(*args: object) -> None:
    print(*args, flush=True)


def _load_config() -> dict:
    path = paths.PROJECT_ROOT / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _is_session_time(now: datetime) -> bool:
    """Inside PSX hours (09:32-15:30 PKT, two legs on Friday)?"""
    return sessions.is_open(now)


def _feed_health(snapshot: dict) -> tuple[bool, str]:
    """v0.20.4: would a human trust this poll? A 200-but-garbage
    response (empty parse, all-zero volume, hours-old stamp) must never
    reach the engine - the Oct-14-class failure. Returns (healthy, reason).

    Three signatures of a dead/stale feed, any one is fatal:
      * coverage collapsed (far fewer quotes than the universe);
      * almost nothing live-priced (price>0 with volume>0 while the
        market is open - a closed/stale page still carries rows);
      * the feed's own receiveTime is impossibly old.
    Thresholds are config-surfaced (min_live_ratio, max_feed_age_min).
    """
    cfg = _load_config()
    quotes = snapshot.get("quotes") or {}
    universe = int(snapshot.get("universeCount") or 0) or len(quotes)
    min_ratio = float(cfg.get("min_live_ratio", 0.6))
    if universe and len(quotes) < min_ratio * universe:
        return False, (
            f"coverage collapsed: {len(quotes)}/{universe} quotes "
            f"(< {min_ratio:.0%})"
        )

    live = sum(
        1
        for q in quotes.values()
        if isinstance(q.get("price"), (int, float))
        and q["price"] > 0
        and isinstance(q.get("volume"), (int, float))
        and q["volume"] > 0
    )
    min_live = int(cfg.get("min_live_quotes", 10))
    if live < min_live:
        return False, (
            f"only {live} live-priced instruments (< {min_live}) "
            f"- stale or closed feed"
        )

    max_age_min = float(cfg.get("max_feed_age_min", 10.0))
    stamp = _parse_snapshot_ts(snapshot.get("receiveTime"))
    if stamp is None:
        return False, "no parseable receiveTime in snapshot"
    age_min = (
        datetime.now(timezone.utc) - stamp
    ).total_seconds() / 60.0
    if age_min > max_age_min:
        return False, f"feed stamp {age_min:.0f} min old (> {max_age_min:.0f})"
    return True, ""


def _parse_snapshot_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


_ALERT_FILE = paths.DATA_DIR / "feed_alerts.json"


def _alert_feed(reason: str) -> None:
    """Telegram the owner about a garbage feed - ONCE per failure class
    per session (anti-spam), independent of GitHub (notify.py talks to
    Telegram directly). Never raises: an alert failure must not kill
    the pass's remaining duties."""
    try:
        state: dict = {}
        if _ALERT_FILE.exists():
            state = json.loads(_ALERT_FILE.read_text(encoding="utf-8"))
        today = sessions.trading_date(datetime.now(timezone.utc)).isoformat()
        key = reason.split(":")[0].split("(")[0].strip()[:40]
        already = key in state.get(today, [])
        state[today] = sorted(set(state.get(today, []) + [key]))
        # date-based pruning: any session key older than 7 days (or not
        # a date at all) is dropped - the file can never grow unbounded
        cutoff = (
            sessions.trading_date(datetime.now(timezone.utc))
            - timedelta(days=7)
        ).isoformat()
        for stale_day in [d for d in state if d < cutoff or "-" not in d]:
            state.pop(stale_day, None)
        _ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ALERT_FILE.write_text(
            json.dumps(state, indent=1), encoding="utf-8"
        )
        if already:
            _print(f"feed alert (already reported today): {reason}")
            return
        import notify

        msg = (
            "⚠️ FEED ALERT - pass refused to decide.\n"
            f"Reason: {reason}\n"
            "Exits are still guarded on this data; entries are OFF "
            "until the next poll. The watchdog/seatbelt will retry."
        )
        ok = notify.send_telegram(msg)
        _print(f"feed alert sent (telegram={ok}): {reason}")
    except Exception as exc:  # noqa: BLE001 - alerting must never kill a pass
        _print(f"feed alert failed (non-fatal): {exc}")


def poll_and_store() -> dict:
    """One feed poll + archive append (mirrors the collector)."""
    import argparse

    import collect_kmiall_snapshots as collector
    import requests

    from psx_core import feed
    from psx_core import universe as universe_mod

    symbols = universe_mod.load()
    http = requests.Session()
    http.headers.update({"User-Agent": "Mozilla/5.0 (sentinel-cloud)"})

    args = argparse.Namespace(
        market="REG", timeout=30.0, min_instruments=feed.MIN_EXPECTED_INSTRUMENTS
    )
    snapshot = collector.poll_once(http, symbols, args)
    path = storage.append_snapshot(snapshot)
    _print(
        f"Poll OK | {len(snapshot.get('quotes') or {})} quotes | "
        f"archived -> {path.name}"
    )
    return snapshot


def check_exits(snapshot: dict) -> int:
    """Fast exit guard against the fresh snapshot's prices."""
    from portfolio import Portfolio

    cfg = _load_config()
    book = _make_book(cfg)
    if not book.open_positions:
        _print("Book flat - no exit checks needed.")
        return 0

    price_map = {
        sym: q["price"]
        for sym, q in (snapshot.get("quotes") or {}).items()
        if isinstance(q.get("price"), (int, float)) and q["price"] > 0
    }
    # v0.20.3: the feed's day-high rides along so a target touched
    # between polls is captured at the next one (attribution: only a
    # high beyond the entry-poll seed, or a fresh session, counts).
    high_map = {
        sym: q["high"]
        for sym, q in (snapshot.get("quotes") or {}).items()
        if isinstance(q.get("high"), (int, float)) and q["high"] > 0
    }
    now = datetime.now(timezone.utc)
    current_date = sessions.trading_date(now).isoformat()
    exits = book.check_exits(
        price_map, current_date,
        high_prices=high_map,
    )
    for pos in exits:
        _print(
            f"EXIT {pos.symbol} @ {pos.exit_price or 0.0:.2f} "
            f"P&L {pos.pnl or 0.0:+.2f} ({pos.exit_reason})"
        )
    if exits or True:
        # Persist the trailing-stop ratchet even when nothing exited.
        book.save()
    _print(f"Book: {len(book.open_positions)} open position(s).")
    return len(exits)


def deliver_events() -> None:
    """Deliver pending BUY/EXIT events (email via the signals issue,
    Telegram as the backup channel).

    EVERY close path must call this. The 2026-09-17 incident: exits
    were written by the sweep/close-out after the last delivering pass,
    so the owner was never told about the SNGP exit. Delivery now
    rides with every closer - at-least-once, deduped by notified.json.
    """
    try:
        import notify

        summary = notify.deliver(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_TOKEN", ""),
        )
        if summary["issue"]:
            _print(
                f"notify: sent {summary['sent']}/{summary['pending']} "
                f"event(s) to issue #{summary['issue']}"
            )
        else:
            _print(f"notify: {summary['pending']} pending, no delivery target.")
    except Exception as exc:  # noqa: BLE001 - delivery must never kill a pass
        _print(f"notify: delivery failed (non-fatal): {exc}")


def close_session() -> int:
    """Closing sweep (v0.18.0): force-close open positions at the last
    prices of today's session.

    The 44-trade forensics: 31 of 44 losses were max-hold closes at
    the NEXT morning's prices - the book slept on positions overnight
    because nobody closed it at the bell. The panel data says same-day
    EOD closes beat overnight holds decisively (worst-session drawdown
    -462% -> -36%). Runs after the session ends (self-guarded: defers
    while the market is open), so the workflow's post-close cron slots
    turn the bot's book flat every evening.
    """
    from portfolio import Portfolio

    now = datetime.now(timezone.utc)
    if sessions.is_open(now):
        _print("Session still open - closing sweep deferred.")
        return 0
    day = sessions.trading_date(now).isoformat()
    last_snap = None
    for label, snap in storage.iter_snapshots():
        if day in label:
            last_snap = snap
    if last_snap is None:
        _print("No snapshot from today's session - nothing to close.")
        deliver_events()  # pending events still deserve delivery
        return 0
    book = _make_book(_load_config())
    if not book.open_positions:
        _print("Book flat - closing sweep no-op.")
        deliver_events()  # pending events still deserve delivery
        return 0
    _print(f"Closing sweep: {len(book.open_positions)} open position(s) at session end.")
    rc = check_exits(last_snap)
    deliver_events()  # v2.0.1: the sweep must tell the owner what it did
    return rc


def _make_book(cfg: dict) -> "Portfolio":
    from portfolio import Portfolio

    return Portfolio(
        profit_target_low=cfg.get("profit_target_low", 2.0),
        profit_target_high=cfg.get("profit_target_high", 3.0),
        max_holding_days=cfg.get("max_holding_days", 1),
        capital=cfg.get("capital", 1_000_000),
        position_size_pct=cfg.get("position_size_pct", 10.0),
        max_loss_pct=cfg.get("max_loss_pct", 2.0),
        # Trailing only TIGHTENS (arms after +1% gain, trails 0.5%
        # below the high) - it never widens the -1% hard stop. Default
        # 0.5 matches config.json; the old 1.5 default predated the
        # universal law and could arm a wider-than-1% trail.
        trailing_stop_pct=cfg.get("trailing_stop_pct", 0.5),
        trailing_stop_activation_pct=cfg.get(
            "trailing_stop_activation_pct", 1.0
        ),
        stale_trade_minutes=cfg.get("stale_trade_minutes", 45.0),
        stale_trade_min_gain_pct=cfg.get("stale_trade_min_gain_pct", 0.2),
        stop_confirmations_required=cfg.get("stop_confirmations_required", 1),
    )


def decide(snapshot: dict) -> None:
    """One full decide cycle, if the book has an entry slot left."""
    from entry_gate import EntryGate, load_max_entries_from_config

    gate = EntryGate(max_entries_per_day=load_max_entries_from_config())
    current_date = sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()
    used = gate.entries_today(current_date)
    if used >= gate.max_entries_per_day:
        _print(
            f"Entry cap reached ({used}/{gate.max_entries_per_day}) - decide skipped."
        )
        return

    import logging

    from live import run_decide

    logger = logging.getLogger("cloud.decide")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        )
        logger.addHandler(handler)

    # run_decide returns the decision as a plain dict (its own JSON
    # shape), not a Decision object.
    decision = run_decide(logger, gate=gate)
    if decision is None:
        _print("Decide cycle failed (build error) - see log above.")
        return
    _print(
        f"DECISION {decision.get('action')} "
        f"{decision.get('symbol') or ''} {decision.get('reason')}"
    )


def main() -> int:
    paths.enable_utf8_stdout()
    paths.ensure_dirs()

    now = datetime.now(timezone.utc)
    _print(f"=== Sentinel cloud pass @ {now.isoformat(timespec='seconds')} ===")
    if "--close-session" in sys.argv:
        return close_session()
    if not _is_session_time(now):
        # Post-close: the only remaining job is the closing sweep -
        # force-close the book at today's last prices (v0.18.0). The
        # 15:34/15:49 PKT crons land here; the sweep self-guards
        # (defers while open, no-ops when the book is flat).
        _print("Market closed - running the closing sweep.")
        return close_session()

    try:
        snapshot = poll_and_store()
    except Exception as exc:  # noqa: BLE001
        _print(f"Poll failed after retries: {exc}")
        # Exits still deserve a pass with the last stored prices if any.
        snapshot = {}
        try:
            day = sessions.trading_date(now).isoformat()
            last_snap = None
            for label, snap in storage.iter_snapshots():
                if day in label:
                    last_snap = snap
            if last_snap is not None:
                snapshot = last_snap
                _print("Using last stored snapshot for exit checks.")
        except Exception:  # noqa: BLE001
            pass
        if not snapshot:
            return 1

    # v0.20.4 feed-health gate: a garbage poll (200-but-empty, all-flat
    # quotes, stale stamp) never reaches the engine. Exits still run -
    # risk-reduction on stale data beats no risk-reduction - but the
    # decide pass is refused and the heartbeat is deliberately not
    # stamped, so the watchdog/seatbelt treat the slot as failed and
    # self-heal by retrying on fresh data.
    feed_ok = True
    if "--skip-feed-check" not in sys.argv:
        feed_ok, feed_reason = _feed_health(snapshot)
        if not feed_ok:
            _print(f"FEED UNHEALTHY - refusing to decide: {feed_reason}")
            _alert_feed(feed_reason)

    exits = check_exits(snapshot)

    # v3.1.0 open bell: one "I am online" card per trading leg, sent
    # after the exit guard so the book line is true. Deduped in
    # v3.4.0 session cards: MARKET OPEN goes to GitHub (primary) AND
    # Telegram (backup), once per leg, per the owner's standing order.
    # data/session_cards.json; silent on holidays, weekends, closed
    # hours and when the kill-switch (session_cards_enabled) is off.
    # Never fatal
    try:
        import session_cards

        card_sent, card_note = session_cards.announce_open(now)
        if card_sent:
            print(f"session card: {card_note}")
    except Exception as card_exc:  # noqa: BLE001
        print(f"session card error (non-fatal): {card_exc}")

    # data/open_bell.json; silent on holidays, weekends, closed hours
    # and when the kill-switch (open_bell_enabled) is off. Never fatal
    # and never raises.
    try:
        import open_bell

        sent, note = open_bell.announce_open(now)
        _print(f"open bell: {note}")
    except Exception as exc:  # noqa: BLE001 - must never kill a pass
        _print(f"open bell: failed (non-fatal): {exc}")

    only_exits = "--exits-only" in sys.argv
    if not only_exits and feed_ok:
        decide(snapshot)
    elif not feed_ok:
        _print(
            f"{exits} exit(s) handled on degraded data; "
            "decide REFUSED (feed unhealthy)."
        )
    else:
        _print(f"--exits-only: {exits} exit(s) handled, decide skipped.")

    # Deliver every new BUY/EXIT to the owner (email via the signals
    # issue, Telegram backup) and regenerate SIGNALS.md. Runs even on
    # poll-failure passes: check_exits above may have written exits.
    deliver_events()

    # Heartbeat: the keeper's trusted freshness signal. GitHub's run
    # metadata marks even SKIPPED passes "success" (2026-09-16 incident:
    # one skip ended the cadence while metadata said all healthy). This
    # stamp only exists when a pass really polled, exited and decided -
    # and v0.20.4: only when the feed passed the health gate (a garbage
    # poll must look FAILED to the watchdog, not healthy).
    if not feed_ok:
        _print(
            "heartbeat: deliberately NOT stamped (unhealthy feed) - "
            "the watchdog/seatbelt will rescue the cadence."
        )
    else:
        try:
            import heartbeat

            heartbeat.stamp()
            _print("heartbeat: stamped.")
        except Exception as exc:  # noqa: BLE001 - must never kill a pass
            _print(f"heartbeat: stamp failed (non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
