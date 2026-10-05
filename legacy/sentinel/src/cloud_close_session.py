"""
THE SENTINEL (PSX KMIALL) - cloud session-closer.

What this is
------------
The end-of-session paperwork, run by GitHub Actions instead of your PC.
One workflow fires ~15 minutes after the PSX close (15:45 PKT on
Mon-Thu, 16:45 on Friday's two-leg schedule), checks out the repo,
closes the paper book for the day and refreshes the next session's
inputs - the same steps the desktop runner performs in its
session-close bookkeeping (live.py: _session_close_bookkeeping).

Why this matters (two real incidents):
  * 2026-09-09: the PC vanished at close; outcomes/lessons for the day
    were lost, and the learning layer trained on a hole.
  * 2026-09-11: the machine slept mid-session. The close-out is the
    one part that must never depend on the trading machine staying up.

What it does, in order (each step isolated; one failure never blocks
the next):
  1. Price the exits - one fresh feed poll gives every open position
     its closing price (a cloud run has no tick snapshots to read).
  2. Force-close open positions (intraday book, nothing overnight).
  3. Fold today's volume/trades into the cross-day EMA baselines.
  4. Refresh the post-close feeds: KSE-100 index history (tomorrow's
     Rule 11 regime input), foreign flow, news sentiment,
     announcements.
  5. Assemble the day's labeled outcomes into the ledger and refresh
     the self-learning layer.

What it deliberately does NOT do: the full multi-day dataset rebuild.
That needs the day's snapshot file (data/snapshots/ is gitignored for
size) and stays the desktop runner's job; the first decide cycle of
your next local session rebuilds today-scoped data anyway.

State round-trip: the workflow commits data/portfolio.json,
data/outcomes.jsonl, data/lessons.json, data/volume_baselines.json and
the regime inputs back to the repo, so your next local session starts
from the completed books.

Usage (local test):  python src/cloud_close_session.py [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import feed, paths, sessions  # noqa: E402


def _log(msg: str) -> None:
    print(f"[cloud-close {datetime.now(timezone.utc).astimezone():%H:%M:%S}] {msg}",
          flush=True)


def _universe() -> list[str]:
    """The KMIALL universe - build_universe_snapshot projects to this."""
    from psx_core import universe
    return universe.load()


def _closing_price_map() -> dict[str, float]:
    """One fresh feed poll -> {symbol: last price} for exit pricing."""
    import requests

    try:
        http = requests.Session()
        market_data = feed.fetch_snapshot(http, timeout=30.0)
        snapshot = feed.build_universe_snapshot(
            market_data, _universe(), feed.DEFAULT_MARKET
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"feed poll failed: {exc}")
        return {}
    prices: dict[str, float] = {}
    for quote in (snapshot.get("quotes") or {}).values():
        sym = quote.get("symbol")
        price = quote.get("price")
        if sym and isinstance(price, (int, float)) and price > 0:
            prices[sym] = float(price)
    _log(f"closing prices for {len(prices)} symbols")
    return prices


def close_intraday_book(trading_date: str) -> None:
    """Steps 1-2: price and force-close any position still open."""
    from portfolio import Portfolio

    cfg = json.loads(
        (paths.PROJECT_ROOT / "config.json").read_text(encoding="utf-8")
    )
    portfolio = Portfolio(
        max_loss_pct=cfg.get("max_loss_pct", 1.5),
        max_holding_days=1,
        trailing_stop_pct=cfg.get("trailing_stop_pct", 0.5),
        trailing_stop_activation_pct=cfg.get(
            "trailing_stop_activation_pct", 1.0
        ),
        stale_trade_minutes=cfg.get("stale_trade_minutes", 0.0),
        stale_trade_min_gain_pct=cfg.get("stale_trade_min_gain_pct", 0.2),
    )
    if not portfolio.open_positions:
        _log("no open positions; book already clean")
        return
    prices = _closing_price_map()
    for position in portfolio.open_positions:
        last_price = prices.get(position.symbol)
        if last_price is None:
            # Never seen today: close flat at entry rather than hang open.
            last_price = position.entry_price
        portfolio.force_close(
            position.symbol,
            last_price,
            trading_date,
            reason="End of session (cloud close)",
        )
        _log(f"EXIT {position.symbol} @ {last_price:.2f} (force-close)")


def update_baselines(trading_date: str) -> None:
    """Step 3: needs the day's cumulative volumes from the last poll."""
    try:
        from baselines import VolumeBaselines

        prices_snapshot = _poll_snapshot_raw(_universe())
        quotes = (prices_snapshot.get("quotes") or {}).values()
        totals = {
            q.get("symbol"): (float(q.get("volume") or 0.0),
                              float(q.get("trades") or 0.0))
            for q in quotes
            if q.get("symbol")
        }
        if totals:
            baselines = VolumeBaselines()
            baselines.record_session(trading_date, totals)
            _log(f"baselines updated for {len(totals)} symbols")
    except Exception as exc:  # noqa: BLE001
        _log(f"baseline update failed: {exc}")


def _poll_snapshot_raw(symbols: list[str]) -> dict:
    import requests

    http = requests.Session()
    market_data = feed.fetch_snapshot(http, timeout=30.0)
    return feed.build_universe_snapshot(
        market_data, symbols, feed.DEFAULT_MARKET
    )


def refresh_regime_inputs() -> None:
    """Step 4: the next session's gates eat these; refresh each alone."""
    try:
        import fetch_index_history
        fetch_index_history.refresh_if_stale(None)
        _log("index history refreshed")
    except Exception as exc:  # noqa: BLE001
        _log(f"index-history refresh failed: {exc}")

    try:
        # The canonical refresh+fold logic lives in the live runner
        # (fetch when stale, append to foreign_flow_history.jsonl).
        from psx_core import logs as _logs
        import live as _live
        if _live._refresh_foreign_flow_history(
            _logs.get_logger("cloud_close", quiet_console=True)
        ):
            _log("foreign flow refreshed")
        else:
            _log("foreign flow already current")
    except Exception as exc:  # noqa: BLE001
        _log(f"foreign-flow refresh failed: {exc}")

    # v4.0.0: the news and announcements refreshes are retired with
    # psxterminal.com (no reachable replacement; the layers were
    # config-gated OFF since v3.0.0 and read as neutral when their
    # files are absent). The corporate-actions refresh below stays:
    # its fetch now raises RetiredSource, caught by the same except.

    try:
        # v0.19.0: corporate actions (book closures / ex-dates / results
        # with EPS) - Rule 25's raw material for tomorrow's session.
        import corporate_actions
        payload = corporate_actions.fetch_corporate_actions()
        closures = sum(
            1
            for e in payload["bySymbol"].values()
            if e.get("book_closure_from") or e.get("ex_date")
        )
        _log(
            f"corporate actions: {payload['records']} records, "
            f"{closures} with closure/ex dates"
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"corporate actions refresh failed: {exc}")


def label_outcomes(trading_date: str) -> None:
    """Step 5: assemble the day's labeled outcomes, then the lessons."""
    try:
        import outcomes_assembler
        written = outcomes_assembler.assemble_day(trading_date)
        _log(f"outcomes labeled: {len(written)}")
    except Exception as exc:  # noqa: BLE001
        _log(f"outcome assembly failed: {exc}")
        return
    # v3.0.0 simplification: the self-teacher is retired. No run
    # rewrites config.json or the lesson stores by itself anymore -
    # the owner tunes the rulebook, the bot follows it. Outcome
    # labelling above stays (the ledger must stay complete).
    try:
        cfg = json.loads(
            (paths.PROJECT_ROOT / "config.json").read_text(encoding="utf-8")
        )
        if (cfg.get("learning") or {}).get("enabled", True):
            import lessons
            summary = lessons.refresh_lessons(trading_date, cfg)
            _log(f"lessons refreshed: {summary}")
        else:
            _log("lessons: skipped (learning disabled in config)")
    except Exception as exc:  # noqa: BLE001
        _log(f"lessons refresh failed: {exc}")


def main(argv=None) -> int:
    paths.enable_utf8_stdout()
    paths.ensure_dirs()
    parser = argparse.ArgumentParser(
        description="Cloud session-closer (GitHub Actions)."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="run the close-out even if the market is still marked open "
             "(for testing outside the workflow).",
    )
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    trading_date = sessions.trading_date(now).isoformat()
    if sessions.is_holiday(sessions.trading_date(now)):
        _log(
            f"{trading_date} is an official PSX holiday - market never "
            "traded; bookkeeping stands down (no force-close at stale "
            "prices, no phantom session)."
        )
        return 0
    if sessions.is_open(now) and not args.force:
        _log("market still open; refusing to close the book mid-session "
             "(use --force to override)")
        return 1
    _log(f"closing the book for {trading_date}")

    # Each step is isolated exactly like the desktop close-out: one
    # failing step must never stop the next session's collection.
    def _run_step(name, fn, *a):
        try:
            fn(*a)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name} failed: {exc}")

    _run_step("intraday close", close_intraday_book, trading_date)
    _run_step("baselines", update_baselines, trading_date)
    _run_step("regime refresh", refresh_regime_inputs)
    _run_step("outcome labelling", label_outcomes, trading_date)

    # v3.0.0 simplification: the market lesson, live lock memory and
    # corpus refresh are retired from the close-out. They built the
    # stores the retired memory layers read; the clean engine does not
    # consume them, so the close-out no longer spends runner minutes
    # maintaining them. (Research scripts remain for manual runs.)

    # v2.0.1 incident fix: the close-out used to write exits and stop -
    # but no pass runs after 20:19 PKT, so the exit email never fired
    # (2026-09-17: SNGP closed, owner never told). The closer must
    # deliver its own events. Telegram rides the same call.
    def _deliver():
        import notify

        summary = notify.deliver(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_TOKEN", ""),
        )
        _log(f"delivery: sent {summary['sent']}/{summary['pending']} event(s)")

    _run_step("signal delivery", _deliver)

    # v3.4.0: MARKET CLOSED card - GitHub (primary) + Telegram (backup)
    # with the day's win/loss summary. Sent after the book is closed so
    # the summary reflects final outcomes. Once per day; never fatal.
    def _close_card():
        import session_cards

        sent, note = session_cards.announce_close(now)
        _log(f"close card: {note}")

    _run_step("market-closed card", _close_card)

    # v3.0.0 simplification: no automatic backtest dispatch. The
    # self-improve trigger fired parameter sweeps that burned the
    # Actions minutes quota; the owner runs any sweep manually when
    # they want one (workflow_dispatch only).
    _log("session close-out complete; the workflow commits the state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
