"""
THE SENTINEL (PSX KMIALL)
Live runner - runs the full pipeline in real-time during market hours.

Architecture:
  1. Wait for market open (or start immediately if already open)
  2. Collect snapshots every 5 seconds (tight HTTP loop)
  3. Every DECIDE_INTERVAL seconds, run build → features → decide
  4. Log every decision, update the portfolio
  5. When the session closes, compact the day's snapshots
  6. Sleep until the next open (handles weekends automatically)

Real-time pricing:
  The ECLEAR broker feed (MKT-FEED socket, read-only) is subscribed
  every 5 seconds. Each poll returns live ticks for the whole KMIALL
  universe plus the broker's shariah list, with the KSE-100 index quote
  riding on the same connection. The 5-second poll interval means
  prices are at most 5 seconds stale - well within the resolution
  needed for intraday ranking.

Entry discipline:
  The 3-entries-per-day cap is enforced by the persistent EntryGate
  (entry_gate.py), keyed by trading date and shared with pipeline.py.
  Exit checks are NOT gated: open positions are monitored until they
  close even after the entry cap is reached.

Usage
-----
    python src/live.py                      # run until session closes
    python src/live.py --decide-interval 30 # decide every 30 seconds
    python src/live.py --dry-run            # collect but don't write/decide
    python src/live.py --test               # test with existing data (no network)
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import feed, logs, paths, sessions, storage

from entry_gate import EntryGate, load_max_entries_from_config

LOGGER_NAME = "live"
DEFAULT_COLLECT_INTERVAL = 5.0
DEFAULT_DECIDE_INTERVAL = 60.0  # rebuild features + decide every 60s
MAX_CONSECUTIVE_FAILURES = 12
RETRY_BACKOFF = (0.5, 1.5)

_STOP_REQUESTED = False
_CONFIRM_PENDING = False

# Stand-aside reasons already announced to the console this session.
# The console carries the greeting, BUY and EXIT calls, and the one
# daily-loss-breaker WAIT - a refusal reason that would otherwise
# repeat every cycle prints at most once.
_announced_refusals: set[str] = set()


def _disable_sleep_while_trading() -> None:
    """
    Best-effort: keep this Windows machine awake for the whole session.

    2026-09-11 evidence: poll records vanish 10:50-14:20 PKT with no
    process exit and no errors - the pattern of a machine that SLEPT.
    While the bot was blind the index fell -2200 and reversed +3800;
    a sleeping machine is an unattended-trading failure mode worth one
    Win32 call. Windows suspends via SetThreadExecutionState when no
    user input arrives; this renews ES_SYSTEM_REQUIRED | ES_CONTINUOUS
    every loop pass. On any non-Windows platform (or failure) this is a
    silent no-op - the bot must run anywhere.
    """
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
    except Exception:  # noqa: BLE001 - non-Windows / restricted: no-op
        pass


def _request_stop(signum, frame) -> None:  # noqa: ARG001
    """
    Ctrl+C handler: confirm before stopping, force-quit on second press.

    Why a prompt instead of silently setting the stop flag: the flag only
    takes effect between cycles, so a bare flag made Ctrl+C *look* dead -
    the console printed nothing and the window had to be killed manually,
    which then interrupted end-of-session bookkeeping mid-flight (the
    2026-09-09 outcomes/lessons were lost exactly that way).

    Behaviour:
      * first Ctrl+C  -> "Stop? [y/N]" prompt; y stops gracefully after
        the current step, Enter/N declines and the bot continues;
      * second Ctrl+C -> immediate KeyboardInterrupt (force quit),
        whether the prompt is open or a graceful stop is already under
        way;
      * no interactive stdin (EOFError, e.g. redirected input) -> treated
        as confirmed, preserving the old graceful behaviour.
    """
    global _STOP_REQUESTED, _CONFIRM_PENDING
    if _STOP_REQUESTED or _CONFIRM_PENDING:
        # Graceful stop already requested (or the question is on screen
        # unanswered): Ctrl+C again means NOW - unwinds through the
        # finally block and exits.
        print("\nForce quit.", flush=True)
        raise KeyboardInterrupt
    _CONFIRM_PENDING = True
    try:
        answer = input(
            "\nCtrl+C - stop The Sentinel? [y/N] "
            "(or press Ctrl+C again to force quit) "
        ).strip().lower()
    except (EOFError, RuntimeError, OSError):
        # Non-interactive stdin: honour the stop request as before.
        answer = "y"
    finally:
        _CONFIRM_PENDING = False
    if answer in ("y", "yes"):
        _STOP_REQUESTED = True
        print(
            "Stopping after the current step... "
            "(press Ctrl+C again to force quit now)",
            flush=True,
        )
    else:
        print("Continuing.", flush=True)


# ---------------------------------------------------------------------------
# Collect one snapshot
# ---------------------------------------------------------------------------

def poll_once(http, symbols: list[str], market: str, timeout: float,
              min_instruments: int) -> dict:
    """Fetch, parse and project one snapshot. Retries transient errors."""
    from psx_core import feed as _feed
    attempts = 1 + len(RETRY_BACKOFF)
    last_error = None
    for attempt in range(attempts):
        try:
            market_data = _feed.fetch_snapshot(
                http, market=market, timeout=timeout,
                min_instruments=min_instruments,
            )
            return _feed.build_universe_snapshot(market_data, symbols, market)
        except Exception as exc:
            last_error = exc
            if attempt < len(RETRY_BACKOFF):
                time.sleep(RETRY_BACKOFF[attempt])
    raise last_error


# ---------------------------------------------------------------------------
# Market-regime inputs (self-healing)
# ---------------------------------------------------------------------------

_CLOSES_RECORDED_DATES: set[str] = set()


def _ensure_regime_inputs(logger) -> None:
    """
    Make sure the market-regime data files exist and are current.

    The close-time refreshes were missed on 2026-09-08/09 when the
    runner was stopped early, so each input also self-heals here: a
    cheap file check every decide cycle, a network fetch only when the
    stored data does not yet cover the last completed session. Every
    step swallows its own failure - a missing regime input degrades the
    corresponding gate to unknown (pass), it never breaks a cycle.
    """
    try:
        import fetch_index_history
        if fetch_index_history.refresh_if_stale(logger):
            logger.info("Index history self-healed at decide cycle.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Index-history self-heal failed: %s", exc)

    try:
        _refresh_foreign_flow_history(logger)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Foreign-flow self-heal failed: %s", exc)


def _refresh_foreign_flow_history(logger) -> bool:
    """
    Retired with psxterminal.com (v4.0.0).

    The FIPI/LIPI institutional-flow fetcher lived on psxterminal.com,
    which is gone from the stack; NCCPL's own site WAF-blocks
    programmatic access. The stored foreign_flow_history.jsonl keeps
    its value as a historical record: the Rule 12b gates read it and
    simply stay dormant when no new rows appear (their no-data path),
    and Rule 12 was demoted to advisory-only in v0.14.1 anyway.

    Kept as a no-op stub because live.py, cloud_close_session.py and
    the workflow logs all call it - deleting it would churn callers
    for nothing. Always reports False ("nothing refreshed").
    """
    del logger
    return False


def _load_latest_snapshot_for_closes() -> dict | None:
    """Parse the newest snapshot of today (used by the fast path)."""
    try:
        path = storage.day_file(
            sessions.trading_date(datetime.now(timezone.utc)).isoformat()
        )
        if not path.exists():
            return None
        with gzip.open(path, "rb") as f:
            last = b""
            for raw in f:
                if raw.strip():
                    last = raw
        return json.loads(last.decode("utf-8")) if last else None
    except Exception:  # noqa: BLE001
        return None


def _record_daily_closes_once(logger, latest, current_date: str) -> None:
    """
    Store today's prior closes (price / (1 + change_pct)) the first time
    a decide cycle sees the day's data - the extension gate's fresh tail.

    change_pct is quoted against the previous close all session, so the
    reconstruction is stable whenever it runs; the once-per-day guard
    just avoids rewriting identical data every cycle.
    """
    if current_date in _CLOSES_RECORDED_DATES:
        return
    try:
        import daily_closes
        stored = daily_closes.record_from_frame(latest, as_of=current_date)
        _CLOSES_RECORDED_DATES.add(current_date)
        logger.info(
            "Prior closes recorded for %s: %d symbols.", current_date, stored
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Daily closes recording failed: %s", exc)


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

def _cheap_breadth_pct() -> float | None:
    """Equal-weight breadth from the freshest stored snapshot - no build.

    Mirrors the engine's definition: OPN instruments with a change
    fraction, share above zero. Costs one small file read; the decide
    cycle's feature build costs ~60 seconds of CPU. Returns None when
    the tape cannot be read (caller must not skip on unknown).
    """
    try:
        path = storage.day_file(
            sessions.trading_date(datetime.now(timezone.utc)).isoformat()
        )
        if not path.exists():
            return None
        with gzip.open(path, "rb") as f:
            last = b""
            for raw in f:
                if raw.strip():
                    last = raw
        if not last:
            return None
        snapshot = json.loads(last.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    quotes = snapshot.get("quotes") or {}
    valid = [
        q for q in quotes.values()
        if q.get("status") == "OPN"
        and isinstance(q.get("changePercent"), (int, float))
    ]
    if len(valid) < 50:
        return None
    up = sum(1 for q in valid if q["changePercent"] > 0)
    return 100.0 * up / len(valid)


def run_decide(logger, gate: EntryGate | None = None) -> dict | None:
    """
    Run one build → features → decide cycle.

    Enforces, in order:
      1. Exit checks on open positions (always run, never capped).
      2. The persistent daily entry cap before any ENTER executes.
         If the cap is reached, the cycle returns a STAND_ASIDE decision
         carrying the reason, so the ledger records why no entry happened.
    """
    import importlib

    # v3.2.0: the fast path below builds a Decision, so the engine
    # module must be loaded before any early return - not lazily
    # midway through the full path only.
    dmod = importlib.import_module("decision_engine")

    # v4.4.3: stamp a local live_py heartbeat on EVERY completed decide
    # cycle (success or stand-aside), not only on the success path after
    # run_decide returns in run_live. The APK phone feed and the keeper
    # watchdog read this during session hours; without it the freshness
    # clock drifts back to the last cloud_bot pass (the 109-min lie at
    # 12:41 PKT on 2026-10-02). Stamped as the LAST thing before each
    # return so a stamp always means a real cycle ran.
    def _live_stamp() -> None:
        try:
            import heartbeat as _hb_r
            _hb_r.stamp(source="live_py")
        except Exception:  # noqa: BLE001 - never break a cycle for freshness
            pass


    if gate is None:
        gate = EntryGate(max_entries_per_day=load_max_entries_from_config())

    # Load config.
    cfg = _read_config()

    # --- Hard-floor fast path (v0.13.1) -----------------------------------
    # Runs BEFORE any heavy work. When the unwaivable 35% breadth floor is
    # blocked AND the book is flat, the full cycle below (~60s CPU across
    # ~4,000 rows) can only ever conclude the same STAND_ASIDE: a flat book
    # has no exits to manage and no entry survives the floor. Read breadth
    # from the raw snapshot instead (milliseconds). ANY open position,
    # unreadable tape, or floor of 0 disables the fast path and runs the
    # full cycle - the fast path can only SKIP work whose result is
    # already determined, never change a decision.
    try:
        import portfolio as pmod  # imported lazily; not a module-level dep
        _fast_floor = float(cfg.get("hard_min_breadth_pct", 35.0))
        _book = pmod.Portfolio(
            profit_target_low=cfg.get("profit_target_low", 2.0),
            profit_target_high=cfg.get("profit_target_high", 3.0),
            max_holding_days=cfg.get("max_holding_days", 1),
            capital=cfg.get("capital", 1_000_000),
            position_size_pct=cfg.get("position_size_pct", 10.0),
            max_loss_pct=cfg.get("max_loss_pct", 2.0),
            trailing_stop_pct=cfg.get("trailing_stop_pct", 0.5),
            trailing_stop_activation_pct=cfg.get(
                "trailing_stop_activation_pct", 1.0
            ),
        )
        _book_flat = not _book.open_positions
    except Exception:  # noqa: BLE001
        _fast_floor, _book_flat = 35.0, False
    if _fast_floor > 0 and _book_flat:
        cheap = _cheap_breadth_pct()
        if cheap is not None and cheap < _fast_floor:
            # Still service the once-per-day prior-closes record from the
            # cheap snapshot so the multi-day-extension gate never runs on
            # a stale tail. (v3.1.1 fix: current_date used to be read here
            # before assignment - an UnboundLocalError crash on every
            # fast-path pass. It is assigned at the top of the block now.)
            current_date = sessions.trading_date(
                datetime.now(timezone.utc)
            ).isoformat()
            if current_date not in _CLOSES_RECORDED_DATES:
                snap = _load_latest_snapshot_for_closes()
                if snap is not None:
                    import pandas as _pd
                    _latest = _pd.DataFrame([
                        {
                            "symbol": q.get("symbol"),
                            "price": q.get("price"),
                            "change_pct": (
                                q["changePercent"] * 100.0
                                if isinstance(
                                    q.get("changePercent"), (int, float)
                                ) else None
                            ),
                        }
                        for q in (snap.get("quotes") or {}).values()
                        if isinstance(q.get("price"), (int, float))
                    ])
                    _record_daily_closes_once(logger, _latest, current_date)
            decision = dmod.Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Hard floor: market breadth {cheap:.1f}% is below "
                    f"the {_fast_floor:.0f}% minimum - no long will be "
                    "taken here, no exceptions (all ledger losses entered "
                    "below it)"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={
                    "breadth_pct": cheap,
                    "gate": "hard_min_breadth_pct",
                    "fast_path": True,
                },
            )
            _log_decision(decision)
            logger.info(
                "Decide cycle (fast path): breadth %.1f%% < %.0f%% floor, "
                "book flat - heavy build skipped.",
                cheap, _fast_floor,
            )
            _live_stamp()
            return decision.to_dict()

    # Self-heal the market-regime inputs (index history, foreign flow)
    # before the decision so the gates run on current evidence.
    _ensure_regime_inputs(logger)

    capital = cfg.get("capital", 1_000_000)

    # The trading date the whole cycle belongs to: the build below is
    # scoped to THIS day only. The full multi-day dataset is rebuilt at
    # session close (see _session_close_bookkeeping), so intraday the
    # engine sees the live session alone - a 5-minute full rebuild every
    # decide cycle would starve the 5s poll loop and kill the 60s
    # momentum lookback (measured: 4-5 min poll gaps on 2026-09-08).
    current_date = sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()

    try:
        # Build dataset + features. The builders print ~60 lines of
        # banners each cycle - useful standalone, pure noise in the live
        # loop. Their stdout is captured and only surfaced on failure.
        # The dataset build is scoped to today (--date): the freshness
        # guard below only ever uses today's rows, and a full rebuild
        # every cycle is what made cycles take 4-5 minutes on 2026-09-08.
        bmod = importlib.import_module("build_intraday_dataset")
        bret = _run_stage_quiet(
            bmod, logger, "Build", extra_args=["--date", current_date]
        )
        if bret != 0:
            _live_stamp()
            return None

        # Compute features
        fmod = importlib.import_module("build_kmiall_features")
        fret = _run_stage_quiet(fmod, logger, "Features")
        if fret != 0:
            _live_stamp()
            return None

        # Load features and run decision engine
        # (dmod is already loaded at the top of run_decide - v3.2.0.)
        pmod = importlib.import_module("portfolio")

        from psx_core import universe as _universe
        _ = _universe  # ensure importable

        import pandas as pd

        csv_path = paths.INTRADAY_CSV
        if not csv_path.exists():
            logger.warning("No dataset found")
            _live_stamp()
            return None

        fdf = fmod.load_dataset(csv_path)
        fdf, feature_summary = fmod.build(fdf)

        scored = int(feature_summary["scoring"]["scored_rows"])
        if scored == 0:
            logger.info("No scored rows, skipping decision")
            _live_stamp()
            return None

        # --- Data-freshness guard ------------------------------------------
        # Signals must come from the CURRENT trading session's snapshots,
        # never from yesterday's data still sitting in the dataset. At a
        # 09:45 start this holds the first cycles in STAND_ASIDE ("warming
        # up") until fresh 09:45+ data exists - the bot analyses the live
        # market as it fills in, then signals. (current_date was
        # established at the top of the cycle, before the build.)
        fresh_rows = fdf[fdf["trading_date"] == current_date]
        fresh_scored = (
            int(fresh_rows["feature_rank_score"].notna().sum())
            if not fresh_rows.empty else 0
        )
        latest_ts = fdf["timestamp"].max()
        if fresh_scored == 0:
            logger.info(
                "No fresh data for %s yet (latest dataset row: %s) - "
                "warming up, standing aside.",
                current_date, latest_ts,
            )
            warmup = dmod.Decision(
                action="STAND_ASIDE",
                reason=(
                    "Warming up: no current-session data yet "
                    f"(latest snapshot {latest_ts})"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={"fresh_scored_rows": 0},
            )
            _log_decision(warmup)
            _live_stamp()
            return warmup.to_dict()

        # --- Market-regime context -------------------------------------------
        # Index trend, foreign-flow streak, per-symbol daily closes -
        # the "be with the market" evidence for rules 11-15. Degrades
        # to unknown (gates pass) on any missing file.
        try:
            import market_regime
            market_ctx = market_regime.load_context(cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Regime context load failed: %s", exc)
            market_ctx = None

        # v2.1.0 Rule 11c: the live index tape. The EOD history Rule 11
        # reads cannot see today; the KSE-100 quote every snapshot carries
        # can. Injected here (not inside load_context) because it lives in
        # the snapshot stream, not the history files. Quotes older than 15
        # minutes are refused - a stale tape must never veto, and a
        # missing one degrades the gate to pass, never to block.
        if market_ctx is not None:
            try:
                _idx_snap = _load_latest_snapshot_for_closes()
                _idx = (_idx_snap or {}).get("index") or {}
                _idx_pct = _idx.get("changePercent")
                if (
                    isinstance(_idx_pct, (int, float))
                    and math.isfinite(_idx_pct)
                ):
                    _fresh = True
                    try:
                        _recv = datetime.fromisoformat(
                            _idx_snap.get("receiveTime", "")
                        )
                        _ts = _idx.get("timestamp")
                        if isinstance(_ts, (int, float)) and _ts > 0:
                            _fresh = (_recv.timestamp() - _ts) <= 900.0
                    except Exception:  # noqa: BLE001
                        pass
                    if _fresh:
                        market_ctx.index_change_pct = float(_idx_pct)
                        market_ctx.index_quote_status = _idx.get("status")
                    else:
                        logger.info(
                            "Index quote stale (ts=%s) - Rule 11c passes",
                            _idx.get("timestamp"),
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live index injection failed: %s", exc)

        # Record today's prior closes once - the extension gate's tail.
        _record_daily_closes_once(
            logger, fdf[fdf["timestamp"] == latest_ts], current_date
        )

        portfolio = pmod.Portfolio(
            profit_target_low=cfg.get("profit_target_low", 2.0),
            profit_target_high=cfg.get("profit_target_high", 3.0),
            max_holding_days=cfg.get("max_holding_days", 1),
            capital=capital,
            position_size_pct=cfg.get("position_size_pct", 10.0),
            max_loss_pct=cfg.get("max_loss_pct", 2.0),
            trailing_stop_pct=cfg.get("trailing_stop_pct", 0.5),
            trailing_stop_activation_pct=cfg.get(
                "trailing_stop_activation_pct", 1.0
            ),
            stale_trade_minutes=cfg.get("stale_trade_minutes", 45.0),
            stale_trade_min_gain_pct=cfg.get(
                "stale_trade_min_gain_pct", 0.2
            ),
        )
        config = dmod.DecisionConfig(
            profit_target_low=portfolio.profit_target_low,
            profit_target_high=portfolio.profit_target_high,
            max_holding_days=portfolio.max_holding_days,
            min_breadth_pct=cfg.get("min_breadth_pct", 40.0),
            index_tape_enabled=cfg.get("index_tape_enabled", True),
            index_tape_floor_pct=cfg.get("index_tape_floor_pct", -0.5),
            max_same_day_change_pct=cfg.get("max_same_day_change_pct", 6.0),
            max_price_position=cfg.get("max_price_position", 0.85),
            min_master_score=cfg.get("min_master_score", 0.55),
            min_evidence_components=cfg.get("min_evidence_components", 5),
            min_day_value=cfg.get("min_day_value", 20_000_000.0),
            circuit_breaker_change_pct=cfg.get(
                "circuit_breaker_change_pct", 9.5
            ),
            trend_filter_enabled=cfg.get("trend_filter_enabled", True),
            min_entry_price=cfg.get("min_entry_price", 10.0),
            require_above_vwap=cfg.get("require_above_vwap", True),
            index_regime_enabled=cfg.get("index_regime_enabled", True),
            index_sma_window=cfg.get("index_sma_window", 20),
            regime_data_veto_enabled=cfg.get("regime_data_veto_enabled", True),
            max_breadth_drop_pct=cfg.get("max_breadth_drop_pct", 10.0),
            foreign_flow_regime_enabled=cfg.get(
                "foreign_flow_regime_enabled", True
            ),
            foreign_flow_streak_days=cfg.get("foreign_flow_streak_days", 3),
            foreign_flow_min_net_usd=cfg.get(
                "foreign_flow_min_net_usd", -5_000_000.0
            ),
            institutional_flow_enabled=cfg.get(
                "institutional_flow_enabled", True
            ),
            institutional_war_divergence=cfg.get(
                "institutional_war_divergence", 2.0
            ),
            institutional_fomo_ratio=cfg.get(
                "institutional_fomo_ratio", 1.35
            ),
            opening_hold_minutes=cfg.get("opening_hold_minutes", 15.0),
            sniper_window_end_minutes=cfg.get(
                "sniper_window_end_minutes", 35.0
            ),
            no_entry_window_start_min=cfg.get(
                "no_entry_window_start_min", 750.0
            ),
            no_entry_window_end_min=cfg.get(
                "no_entry_window_end_min", 890.0
            ),
            chase_penalty_per_pct=cfg.get("chase_penalty_per_pct", 0.08),
            chase_penalty_cap=cfg.get("chase_penalty_cap", 0.25),
            chase_hard_veto_enabled=cfg.get("chase_hard_veto_enabled", True),
            chase_veto_max_change_pct=cfg.get(
                "chase_veto_max_change_pct", 8.0
            ),
            dead_zone_veto_enabled=cfg.get("dead_zone_veto_enabled", True),
            dead_zone_max_change_pct=cfg.get(
                "dead_zone_max_change_pct", 2.0
            ),
            dead_zone_max_score=cfg.get("dead_zone_max_score", 0.70),
            tp_stepdown_minutes=cfg.get("tp_stepdown_minutes", 150.0),
            max_entry_rsi=cfg.get("max_entry_rsi", 80.0),
            money_tape_recovery_enabled=cfg.get(
                "money_tape_recovery_enabled", True
            ),
            money_tape_min_vw_change_pct=cfg.get(
                "money_tape_min_vw_change_pct", 0.0
            ),
            money_tape_min_slope_30m=cfg.get(
                "money_tape_min_slope_30m", 1.0
            ),
            recovery_mode_enabled=cfg.get("recovery_mode_enabled", True),
            recovery_min_off_low_pct=cfg.get(
                "recovery_min_off_low_pct", 3.0
            ),
            score_ceiling_veto=cfg.get("score_ceiling_veto", True),
            score_ceiling=cfg.get("score_ceiling", 0.70),
            recovery_breadth_arm_pct=cfg.get(
                "recovery_breadth_arm_pct", 70.0
            ),
            recovery_slope_30m=cfg.get("recovery_slope_30m", 3.0),
            recovery_max_day_change_pct=cfg.get(
                "recovery_max_day_change_pct", 8.0
            ),
            sector_guard_enabled=cfg.get("sector_guard_enabled", True),
            sector_guard_max_drop_pct=cfg.get(
                "sector_guard_max_drop_pct", 2.0
            ),
            max_positions_per_sector=cfg.get("max_positions_per_sector", 1),
            max_multi_day_gain_pct=cfg.get("max_multi_day_gain_pct", 15.0),
            strong_horse_enabled=cfg.get("strong_horse_enabled", True),
            strong_horse_min_outperformance_pct=cfg.get(
                "strong_horse_min_outperformance_pct", 3.0
            ),
            strong_horse_min_score=cfg.get("strong_horse_min_score", 0.62),
            strong_horse_max_same_day_change_pct=cfg.get(
                "strong_horse_max_same_day_change_pct", 9.0
            ),
            confirmation_enabled=cfg.get("confirmation_enabled", True),
            confirmation_at_high_pct=cfg.get(
                "confirmation_at_high_pct", 1.5
            ),
            confirmation_fresh_minutes=cfg.get(
                "confirmation_fresh_minutes", 20.0
            ),
            recovery_breadth_pct=cfg.get("recovery_breadth_pct", 55.0),
            min_sector_money_flow=cfg.get("min_sector_money_flow", 0.70),
            min_bid_ask_balance=cfg.get("min_bid_ask_balance", 0.50),
            hard_min_breadth_pct=cfg.get("hard_min_breadth_pct", 35.0),
            require_positive_day_change=cfg.get(
                "require_positive_day_change", True
            ),
            max_entry_off_low_pct=cfg.get("max_entry_off_low_pct", 3.0),
            recovery_max_entry_off_low_pct=cfg.get(
                "recovery_max_entry_off_low_pct", 6.0
            ),
        )

        # Self-learning overlay: what the bot has learned from its own
        # labeled outcomes so far (symbol blacklist, score scaling,
        # conviction-gate adjustments). Load errors degrade to no
        # lessons - learning must never break a trading cycle.
        try:
            import lessons as lessons_mod
            lessons_view = lessons_mod.load_lessons(cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lessons load failed (continuing without): %s", exc)
            lessons_view = {}

        # v2.6.0 - the daily market-learner overlay (dead/trending
        # symbols confirmed by the rolling session lessons). Same
        # degradation rule: a failed read trades uninformed, never
        # breaks the cycle.
        # v3.0.0 simplification: the overlay only rides when the owner
        # re-arms it (config "market_learner_enabled": true). The clean
        # engine trades the tape, not a learned symbol list.
        if cfg.get("market_learner_enabled", False):
            try:
                import market_learner
                mkt = market_learner.load_market_lessons()
                lessons_view["market_dead_symbols"] = mkt["dead_confirmed"]
                lessons_view["market_trend_symbols"] = mkt["trend_confirmed"]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Market lessons load failed (continuing without): %s", exc
                )

        engine = dmod.DecisionEngine(config, capital=capital, lessons=lessons_view)

        # v0.19.0 corporate actions: hand the engine the stored map so
        # Rule 25 (book-closure veto) and the fresh-results evidence
        # can act. Load failure = layer inert, decide proceeds as before.
        # v3.0.0 simplification: inert unless the owner re-arms it
        # (config "corporate_actions_veto_enabled": true).
        if cfg.get("corporate_actions_veto_enabled", False):
            try:
                import corporate_actions as _ca
                engine.corporate_actions = _ca.load_map() or None
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Corporate-actions load failed (inert): %s", exc
                )

        # Check exits on existing positions first - always, regardless of
        # the entry cap. A capped day still monitors open positions.
        # (latest_ts and current_date were established above, post-guard.)
        latest = fdf[fdf["timestamp"] == latest_ts]
        price_map = {}
        if "price" in latest.columns:
            price_map = dict(zip(latest["symbol"], latest["price"]))
        # v0.20.3: the session high rides along - a target touched
        # between polls fills on the touch (limit-order reality),
        # attributed via the entry-poll seed in the portfolio.
        high_map = (
            dict(zip(latest["symbol"], latest["high"]))
            if "high" in latest.columns else {}
        )

        exits = portfolio.check_exits(
            price_map, current_date,
            high_prices=high_map,
        )
        for pos in exits:
            _announce(
                "EXIT {sym} @ {price:.2f}  P&L {pnl:+.2f} ({reason})".format(
                    sym=pos.symbol, price=pos.exit_price,
                    pnl=pos.pnl or 0.0, reason=pos.exit_reason,
                )
            )
            logger.info(
                "EXIT %s @ %.2f, P&L %.2f (%s)",
                pos.symbol, pos.exit_price, pos.pnl, pos.exit_reason,
            )

        # Daily-loss circuit breaker: repeated losing exits within one
        # session mean the tape is not what the entry filters believed -
        # no further entries today. Exits stay monitored regardless.
        breaker_losses = int(cfg.get("daily_loss_breaker_losses", 2))
        if breaker_losses > 0:
            losses_today = portfolio.losing_exits_today(current_date)
            if losses_today >= breaker_losses:
                decision = dmod.Decision(
                    action="STAND_ASIDE",
                    reason=(
                        f"Daily loss breaker: {losses_today} losing exits "
                        f"today (>= {breaker_losses}) - the tape is not "
                        "what the filters believed, no new entries until "
                        "the next market day. Exits stay monitored."
                    ),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    metadata={
                        "gate": "daily_loss_breaker",
                        "losing_exits_today": losses_today,
                        "breaker_threshold": breaker_losses,
                    },
                )
                _log_decision(decision)
                _live_stamp()
                return decision.to_dict()

        # Entry gate: stop here once the day's entries are used up.
        # A cap of 0 is the owner's explicit entry PAUSE (2026-09-21):
        # the engine still evaluates and logs what it would have done,
        # but no entry can execute until the owner lifts the pause.
        entries_used = gate.entries_today(current_date)
        if not gate.allows_entry(current_date):
            state = (
                "entries PAUSED by owner"
                if gate.max_entries_per_day == 0
                else "Daily entry limit reached"
            )
            decision = dmod.Decision(
                action="STAND_ASIDE",
                reason=(
                    f"{state} "
                    f"({entries_used}/{gate.max_entries_per_day})"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={"entries_today": entries_used},
            )
            _log_decision(decision)
            _live_stamp()
            return decision.to_dict()

        decision = engine.evaluate(
            fdf,
            held_symbols=portfolio.open_symbols,
            context=market_ctx,
        )

        # v4.1.0 RANKING LAYER (owner's order 2026-09-30): the 8-feature
        # book with ONLY the 4 legal vetoes. When enabled it RE-RANKS
        # the engine's decision: an ENTER from the legacy engine is
        # confirmed only if the same symbol also tops the 8-feature
        # pool; a legacy STAND_ASIDE is upgraded only never - the
        # ranking layer can veto, not invent. Disabled by default in
        # config (ranking_8f_enabled) until walk-forward proves it.
        if (
            cfg.get("ranking_8f_enabled", False)
            and decision.action == "ENTER"
            and decision.symbol
        ):
            try:
                import ranking as rk
                # The dataset timestamps are UTC (coerce_dtypes); the
                # session clock is PKT (owner's law 1). Convert to PKT
                # BEFORE the minute math: 09:30 PKT open = minute 0.
                _ts_pkt = latest["timestamp"].iloc[0].tz_convert(
                    "Asia/Karachi"
                )
                session_minutes = (
                    _ts_pkt.hour * 60.0 + _ts_pkt.minute - 570.0
                )
                fb = rk.build_features(latest, session_fraction_left=None)
                fb = rk.score_frame(fb)
                breadth = (
                    float(latest["breadth_pct"].iloc[0])
                    if "breadth_pct" in latest.columns
                    and pd.notna(latest["breadth_pct"].iloc[0]) else None
                )
                pool, rk_vetoed = rk.eligible_pool(
                    fb, breadth_pct=breadth, minute_of_session=session_minutes
                )
                rk_res = rk.rank_and_pick(pool, min_score=0.0)
                top_sym = rk_res.signal["symbol"] if rk_res.signal else None
                if top_sym != decision.symbol:
                    reason = (
                        f"8-feature rank veto: engine chose {decision.symbol} "
                        f"but the 8-feature pool ranks {top_sym or 'nothing'} first "
                        f"({len(rk_vetoed)} vetoed) - standing aside"
                    )
                    _announce(reason)
                    decision = dmod.Decision(
                        action="STAND_ASIDE",
                        reason=reason,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        metadata={
                            "gate": "ranking_8f",
                            "engine_symbol": decision.symbol,
                            "rank_top": top_sym,
                            "ranked": rk_res.ranked[:5],
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - ranking must never break the cycle
                _log_only(f"ranking layer skipped (non-fatal): {exc}")

        # Execute entry.
        if decision.action == "ENTER" and decision.symbol:
            portfolio.open_position(
                symbol=decision.symbol,
                entry_price=decision.price,
                entry_date=current_date,
                target_price=decision.profit_target_price,
                entry_ts=decision.timestamp,
                # v2.1.0: stamp what the engine knew at pick time, so
                # the closed ledger can finally be mined feature vs
                # outcome (the 45-trade forensics had to work around
                # its absence).
                entry_score=decision.score,
                entry_change_pct=(
                    decision.metadata.get("entry_change_pct")
                    if isinstance(decision.metadata, dict) else None
                ),
                entry_breadth_pct=(
                    decision.metadata.get("breadth_pct")
                    if isinstance(decision.metadata, dict) else None
                ),
                # v0.20.3: the day high on the entry poll - the seed
                # that makes later touch claims attributable to time
                # we actually held the stock.
                high_at_entry=(
                    high_map.get(decision.symbol)
                    if isinstance(decision.metadata, dict) else None
                ),
            )
            used = gate.record_entry(current_date)
            _announce(
                "BUY {sym} @ {price:.2f}  target {target:.2f} "
                "+{tpct:.1f}%  "
                "qty {qty}  [score {score:.4f} | entry {used}/{cap} today]".format(
                    sym=decision.symbol, price=decision.price,
                    target=decision.profit_target_price,
                    tpct=decision.profit_target_pct or 0.0,
                    qty=decision.quantity, score=decision.score,
                    used=used, cap=gate.max_entries_per_day,
                )
            )
            logger.info(
                "ENTER %s @ %.2f, target %.2f, qty=%d, alloc=Rs.%.0f "
                "(score=%.4f, entry %d/%d today)",
                decision.symbol, decision.price,
                decision.profit_target_price, decision.quantity,
                decision.capital_alloc, decision.score,
                used, gate.max_entries_per_day,
            )

        _log_decision(decision)
        _live_stamp()
        return decision.to_dict()

    except Exception as exc:
        logger.warning("Decide cycle failed: %s", exc)
        _live_stamp()
        return None


class _ResilientStdout:
    """stdout wrapper that survives a dead console pipe.

    The console owns this process's stdout pipe; if the console dies
    (or its window is closed), prints raise BrokenPipeError/OSError
    which would otherwise kill the bot mid-session. Errors are
    swallowed - console output is cosmetic, the log files are the
    durable record.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, s):
        try:
            return self._stream.write(s)
        except (BrokenPipeError, OSError, ValueError):
            return len(s)

    def flush(self):
        try:
            self._stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _announce(text: str) -> None:
    """
    Print one console line with a timestamp.

    The live runner's logger is quiet on console (file records all);
    trade calls, waits, and the session summary are announced here -
    the only things the user sees.
    """
    print(f"{datetime.now(timezone.utc).astimezone().strftime('%H:%M:%S')}  {text}",
          flush=True)


def _log_only(text: str, logger=None) -> None:
    """
    Operational chatter (gate config, bookkeeping, waits that repeat
    every cycle): recorded in the log file, never on the console. The
    console carries the greeting, BUY/EXIT calls, and the session
    summary - nothing else.
    """
    if logger is not None:
        logger.info(text)


def _stop_or_file(logger=None) -> bool:
    """
    True when a graceful stop was requested - by Ctrl+C signal OR by
    the web console's stop file (logs/bot.stop). The file is consumed
    when seen. Signals are unreliable across Windows child processes,
    so the console uses the file; both paths announce on the console.
    """
    if _STOP_REQUESTED:
        return True
    f = paths.LOGS_DIR / "bot.stop"
    if f.exists():
        f.unlink(missing_ok=True)
        if logger is not None:
            logger.info("Stop file detected - stopping gracefully.")
        _announce(
            "Stop requested from the web console - shutting down "
            "after this cycle."
        )
        return True
    return False


def _is_chatter(reason: str) -> bool:
    """
    Should this STAND_ASIDE reason stay off the console?

    Console-visible refusals are the ones that explain a decision the
    user could act on (conviction gate, breadth, regime) - and even
    those only once, deduplicated by _announced_refusals.

    The enriched reasons (recovery-day explanations, regime lines,
    horse-gate verdicts) carry "standing aside" style context the
    user must see once; plain "No eligible candidates after
    filtering" without context stays silent - it repeats every cycle
    and says nothing actionable.
    """
    lower = reason.lower()
    # Plain, contextless refusals: chatter.
    plain = (
        "no eligible candidates after filtering" in lower
        or "limit reached" in lower
        or "warming up" in lower
        or "no current-session" in lower
        or "no data at latest timestamp" in lower
        or "min since open" in lower
        or "minutes since open" in lower
        or "bookkeeping" in lower
    )
    if plain:
        # An enriched variant names its gate and carries market
        # context ("Recovery day (...)", "no strong horse (...)").
        # Those print once via the dedupe set even though they
        # contain the plain phrase.
        enriched_markers = (
            "recovery day" in lower
            or "no strong horse" in lower
            or "breadth" in lower
            or "downtrend" in lower
        )
        return not enriched_markers
    return False


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def _greeting(moment: datetime) -> str:
    """
    Time-of-day greeting in Pakistan local time - the session's clock,
    not the machine's. 12:00-13:59 reads 'afternoon', 18:00-23:59
    'evening', otherwise 'morning'. Sentence case: only 'Good' is
    capitalised.
    """
    hour = sessions.to_pkt(moment).hour
    if 12 <= hour < 18:
        word = "afternoon"
    elif hour >= 18:
        word = "evening"
    else:
        word = "morning"
    return f"Good {word}, Mr. Rehan."


def _market_status_line(now: datetime, ignore_schedule: bool = False) -> str:
    """
    One human sentence for the market state at startup.

    ignore_schedule (--ignore-schedule) reports the real state but
    qualifies it, so the line never lies about why the bot is polling a
    closed market.
    """
    leg = sessions.current_leg(now)
    if leg is not None:
        end = sessions.leg_end(now)
        return (
            f"Market is OPEN (leg {leg.index}) - scanning until "
            f"{end.strftime('%H:%M')} PKT."
        )
    nxt = sessions.next_open(now)
    if sessions.is_trading_day(sessions.to_pkt(now).date()):
        base = (
            f"Market is CLOSED - pre-open. First scan at "
            f"{nxt.strftime('%H:%M')} PKT."
        )
    else:
        base = (
            f"Market is CLOSED - next session "
            f"{nxt.strftime('%a %Y-%m-%d %H:%M')} PKT."
        )
    if ignore_schedule:
        base += " Polling anyway (--ignore-schedule)."
    return base


def _startup_banner(
    logger,
    gate: "EntryGate",
    now: datetime,
    *,
    universe_size: int | None = None,
    ignore_schedule: bool = False,
    args: argparse.Namespace | None = None,
) -> None:
    """
    The one thing the console says before the first decision.

    Without it the terminal sits silent through warm-up - polls and
    builds go to the log file only, and early WAIT lines are
    deliberately suppressed - which reads as a hung process. Everything
    announced here is already true at startup; nothing is promised
    about the session ahead.
    """
    config = _read_config()
    cap = gate.max_entries_per_day
    entries_used = gate.entries_today(gate.today_key(now))
    # The banner should state the cadence the loop actually uses (the
    # web console may pass a slower interval to spare the machine).
    decided_interval = int(
        getattr(args, "decide_interval", DEFAULT_DECIDE_INTERVAL) or 0
    ) or int(DEFAULT_DECIDE_INTERVAL)

    _announce("")
    _announce("=" * 72)
    _announce(f"{_greeting(now)} The Sentinel is online and looking "
              "for signals for you.")
    _announce(_market_status_line(now, ignore_schedule))
    _announce(
        f"Entries capped at {cap}/day ({entries_used} used) - "
        "you will only see BUY and EXIT calls here. "
        "Everything else is written to the log."
    )
    _announce("=" * 72)
    _announce("")

    logger.info(
        "Startup banner shown. Entries today: %d/%d. Config: %s",
        entries_used, cap, _summarize_config(config),
    )
    # Gate configuration detail the console no longer carries - it is
    # operational context, not a trade call.
    logger.info("Trend filter: %s", json.dumps({
        "trend_filter_enabled": config.get("trend_filter_enabled", True),
        "require_above_vwap": config.get("require_above_vwap", True),
    }))
    logger.info("Regime: %s", _regime_banner_line(config) or "n/a")
    logger.info(
        "Strong-horse: enabled=%s outperformance=%.0f score=%.2f",
        config.get("strong_horse_enabled", True),
        config.get("strong_horse_min_outperformance_pct", 3.0),
        config.get("strong_horse_min_score", 0.62),
    )
    logger.info(
        "Learning: %s", "ON" if (config.get("learning") or {}).get(
            "enabled", True
        ) else "OFF",
    )


def _regime_banner_line(config: dict) -> str:
    """
    One console sentence describing the market regime the entries will
    face. Reads files only (safe at startup, before any poll); any
    missing input shortens the line rather than blocking startup.
    """
    try:
        import market_regime
        ctx = market_regime.load_context(config)
    except Exception:  # noqa: BLE001
        return "Market regime: unknown (context unavailable - gates dormant)"

    parts = []
    if ctx.index_last_close is not None and ctx.index_sma is not None:
        pct = (ctx.index_last_close / ctx.index_sma - 1.0) * 100.0
        state = (
            "BELOW avg - market downtrend, longs stand aside"
            if ctx.index_below_sma
            else "above avg - market uptrend"
        )
        parts.append(
            f"KSE-100 {ctx.index_last_close:,.0f} vs "
            f"{ctx.index_window}-session avg {ctx.index_sma:,.0f} "
            f"({pct:+.1f}%) - {state}"
        )
    elif getattr(ctx, "index_history_stale", False):
        parts.append(
            "KSE-100 history STALE "
            f"(newest {ctx.index_history_newest or 'none'}, expected "
            f"{ctx.index_history_expected or 'unknown'}) - "
            "entries vetoed until the data heals"
        )
    else:
        parts.append("KSE-100 history not loaded (index gate dormant)")

    if ctx.foreign_flow_streak is not None and ctx.foreign_flow_streak > 0:
        # Advisory since v0.14.1 - the read is displayed, never a veto.
        parts.append(
            f"foreign net selling {ctx.foreign_flow_streak} sessions (advisory)"
        )

    return "Market regime: " + " | ".join(parts)


def _summarize_config(config: dict) -> str:
    """One compact line of the tunables that shape today's behaviour."""
    return (
        f"capital={config.get('capital', 1_000_000):,} "
        f"position_size_pct={config.get('position_size_pct', 10.0)} "
        f"max_loss_pct={config.get('max_loss_pct', 2.0)} "
        f"profit_target_high={config.get('profit_target_high', 3.0)}"
    )


_CONFIG_CACHE: tuple[float, dict] | None = None
_CONFIG_CACHE_TTL = 30.0  # seconds; a live edit lands within one minute


def _read_config() -> dict:
    """Read config.json, cached briefly.

    This runs inside the 5-second poll loop (fast exit guard), so it
    must not hit disk every call - 700+ pointless reads per session.
    A 30-second TTL keeps operator edits effective quickly.
    """
    global _CONFIG_CACHE
    now = time.monotonic()
    if _CONFIG_CACHE is not None and now - _CONFIG_CACHE[0] < _CONFIG_CACHE_TTL:
        return _CONFIG_CACHE[1]
    config_path = paths.PROJECT_ROOT / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    _CONFIG_CACHE = (now, cfg)
    return cfg


def _drop_process_priority() -> None:
    """Best-effort: run below normal priority on Windows.

    The decide cycle rebuilds the full feature frame every cycle and
    legitimately burns up to half a core; the owner's PC must never
    feel it. BELOW_NORMAL_PRIORITY_CLASS + background mode makes the
    OS yield to everything the user does while leaving the bot's own
    timing intact (it is the only heavy process during a session).
    No-op on other platforms.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        import ctypes.wintypes as wt
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wt.HANDLE
        k.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
        k.SetPriorityClass.restype = wt.BOOL
        handle = k.GetCurrentProcess()
        # BELOW_NORMAL_PRIORITY_CLASS: yields to everything the user does.
        k.SetPriorityClass(handle, 0x00004000)
    except Exception:  # noqa: BLE001
        pass


def _log_decision(decision) -> None:
    """Append one decision to logs/decisions.jsonl."""
    log_path = paths.LOGS_DIR / "decisions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            **decision.to_dict(),
        }, default=str) + "\n")


def _run_stage_quiet(
    module,
    logger,
    label: str,
    extra_args: list[str] | None = None,
) -> int:
    """
    Run a build stage with its console output captured.

    Standalone, build_intraday_dataset and build_kmiall_features print
    full report banners - correct for `python src/...` runs, pure noise
    once per minute inside the live loop. Here their stdout/stderr is
    swallowed; on failure it is logged verbatim so nothing is lost, and
    the pandas PerformanceWarning spam is suppressed regardless.

    extra_args are appended to the stage's argv (e.g. --date for the
    scoped live rebuild).
    """
    import contextlib
    import io
    import warnings

    buffer = io.StringIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stdout(buffer), \
                    contextlib.redirect_stderr(buffer):
                returncode = module.main(list(extra_args or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s stage crashed: %s", label, exc)
        return 1

    if returncode != 0:
        output = buffer.getvalue().strip()
        if output:
            logger.warning(
                "%s stage failed (code %d):\n%s", label, returncode, output
            )
    return returncode


def _session_close_bookkeeping(logger) -> None:
    """
    Everything that happens once, at session close:

      1. Intraday force-close: any position still open is closed at its
         last seen price with reason "End of session (intraday)".
      2. Baseline update: fold today's per-symbol total volume/trades
         into the cross-day EMA (src/baselines.py).
      3. Full dataset + feature rebuild (all dates): during the session
         the decide cycle rebuilds only today (--date) so the 5s poll
         loop is never starved; at close the canonical multi-day
         dataset is rebuilt from the completed snapshots so the
         validator and offline research see the whole history.
      4. Event-feed refreshes: foreign flow, news sentiment, and
         announcements publish after close; pull them for the next
         session.
      5. Session summary: print and persist the day's full report of
         every ENTER and STAND_ASIDE (src/session_summary.py).

    Each step logs and continues on failure - a broken step here must
    not stop the next session's collection.
    """
    from portfolio import Portfolio

    current_date = sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()

    # --- 1. Intraday force-close ------------------------------------------
    try:
        portfolio = Portfolio(
            max_loss_pct=2.0,
            max_holding_days=1,
            trailing_stop_pct=1.5,
            trailing_stop_activation_pct=1.0,
        )
        # Last seen price per symbol, from the freshest snapshot on disk.
        price_map = _latest_price_map()
        for position in portfolio.open_positions:
            last_price = price_map.get(position.symbol)
            if last_price is None:
                # No price seen today at all: close at entry (flat).
                last_price = position.entry_price
            portfolio.force_close(
                position.symbol,
                last_price,
                current_date,
                reason="End of session (intraday)",
            )
            _announce(
                "EXIT {sym} @ {price:.2f}  (end of session force-close)".format(
                    sym=position.symbol, price=last_price,
                )
            )
            logger.info(
                "SESSION-CLOSE EXIT %s @ %.2f (intraday force-close)",
                position.symbol, last_price,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session-close exits failed: %s", exc)

    # --- 2. Baseline update -------------------------------------------------
    try:
        from baselines import VolumeBaselines
        baselines = VolumeBaselines()
        totals = _day_volume_totals()
        if totals:
            baselines.record_session(current_date, totals)
            logger.info(
                "Baselines updated for %d symbols (%s).",
                len(totals), current_date,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Baseline update failed: %s", exc)

    # --- 3. Full dataset + feature rebuild (all dates) -------------------
    # Reverses the intraday scoping from run_decide: the snapshots for
    # the day are now complete, so rebuild the canonical multi-day
    # dataset and features once, at close. Slow is fine here - it runs
    # once per session, not every minute.
    try:
        import importlib
        bmod = importlib.import_module("build_intraday_dataset")
        bret = _run_stage_quiet(bmod, logger, "Full rebuild: dataset")
        if bret == 0:
            fmod = importlib.import_module("build_kmiall_features")
            fret = _run_stage_quiet(fmod, logger, "Full rebuild: features")
            if fret == 0:
                logger.info("Full multi-day rebuild completed.")
            else:
                logger.warning("Full feature rebuild failed (code %d).", fret)
        else:
            logger.warning("Full dataset rebuild failed (code %d).", bret)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Full rebuild failed: %s", exc)

    # --- 4. Event-feed refreshes (post-close data) -------------------------
    # Foreign flow, news sentiment, and announcements are published
    # after close; refresh each for the next session. Each step logs
    # independently - one failing source must not stop the others.
    try:
        _refresh_foreign_flow_history(logger)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Foreign-flow refresh failed: %s", exc)

    # KSE-100 EOD history for tomorrow's regime gate (index vs average).
    try:
        import fetch_index_history
        fetch_index_history.refresh_if_stale(logger)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Index-history refresh failed: %s", exc)

    try:
        import fetch_news_sentiment
        result = fetch_news_sentiment.fetch_news_sentiment()
        out = paths.DATA_DIR / "news_sentiment.json"
        out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            "News sentiment refreshed: %d stories, %d symbols tagged.",
            result["storiesParsed"], len(result["bySymbol"]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("News refresh failed: %s", exc)

    try:
        import fetch_announcements
        result = fetch_announcements.fetch_announcements()
        out = paths.DATA_DIR / "announcements.json"
        out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            "Announcements refreshed: %d symbols with notices.",
            len(result["bySymbol"]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Announcements refresh failed: %s", exc)

    # --- 5. The day's summary - every call the bot made, one report ------
    # Runs LAST so the force-closed exits above are included in it.
    try:
        import session_summary
        summary = session_summary.build_summary(current_date)
        report = session_summary.render_text(summary)
        logger.info("Session summary:\n%s", report)
        # The one place the full report is printed: end of day.
        _announce("")
        _announce("=" * 72)
        for line in report.splitlines():
            _announce(line)
        _announce("=" * 72)
        # Persist next to the other logs as well.
        out = paths.LOGS_DIR / f"session_summary_{current_date}.json"
        out.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session summary failed: %s", exc)

    # --- 6. Calibration outcomes - the Tier-3 dataset ---------------------
    # Labels every executed signal with its triple-barrier outcome. Pure
    # post-processing of files written above; failure here can never
    # affect trading.
    try:
        import outcomes_assembler
        written = outcomes_assembler.assemble_day(current_date)
        logger.info("Calibration outcomes appended: %d", len(written))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Outcomes assembly failed: %s", exc)

    # --- 7. Self-learning: fold today's outcomes into lessons -------------
    # Runs LAST so it sees the labels written above. Tomorrow's decide
    # cycles apply whatever was learned (blacklist, score scale, gate
    # adjustment) - the bot's own trades are its teacher.
    # v3.0.0 simplification: the auto-teacher is OFF (config learning
    # disabled). Outcomes keep being labeled - the ledger stays complete
    # - but no run rewrites how the engine decides by itself.
    try:
        import lessons as lessons_mod
        cfg = _read_config()
        if not (cfg.get("learning") or {}).get("enabled", True):
            logger.info(
                "Lessons refresh skipped (learning disabled in config)."
            )
        else:
            lessons = lessons_mod.refresh_lessons(current_date, cfg)
            blacklisted = sorted(lessons.get("blacklisted", {}))
            meta = lessons.get("meta") or {}
            if blacklisted:
                _announce(
                    "Lesson: blacklisted " + ", ".join(blacklisted)
                    + " (persistent losers - excluded from future entries)."
                )
            if meta.get("should_tighten"):
                _announce(
                    "Lesson: recent calls stopped working "
                    f"(profit rate {meta.get('profit_rate', 0):.0%} over "
                    f"{meta.get('window_n', 0)} trades) - conviction gate "
                    "tightened for the next session."
                )
            logger.info(
                "Lessons refreshed: labeled=%d blacklisted=%s score_scale=%s "
                "tighten=%s",
                lessons.get("labeled", 0),
                blacklisted,
                bool(lessons.get("score_scale")),
                bool(meta.get("should_tighten")),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lessons refresh failed: %s", exc)


def _latest_price_map() -> dict[str, float]:
    """Last seen price per symbol from the freshest stored snapshot."""
    try:
        import build_intraday_dataset as bmod

        csv_path = paths.INTRADAY_CSV
        if not csv_path.exists():
            return {}
        df = bmod.load_dataset(csv_path) if hasattr(bmod, "load_dataset") else None
        if df is None:
            return {}
        latest_ts = df["timestamp"].max()
        latest = df[df["timestamp"] == latest_ts]
        return dict(zip(latest["symbol"], latest["price"]))
    except Exception:  # noqa: BLE001
        return {}


def _day_volume_totals() -> dict[str, tuple[float, float]]:
    """
    Per-symbol (total_volume, total_trades) for the closing session, from
    the intraday dataset (cumulative feed: the last row of the day holds
    the day total).
    """
    try:
        import pandas as pd

        csv_path = paths.INTRADAY_CSV
        if not csv_path.exists():
            return {}
        df = pd.read_csv(csv_path, usecols=["symbol", "volume", "trades"])
        totals: dict[str, tuple[float, float]] = {}
        for symbol, group in df.groupby("symbol"):
            last = group.dropna().iloc[-1] if not group.dropna().empty else None
            if last is None:
                continue
            totals[symbol] = (float(last["volume"]), float(last["trades"]))
        return totals
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_live(args) -> int:
    # Quiet console: the logger's file handler still records EVERYTHING
    # (polls, refreshes, builds at DEBUG/INFO); the terminal shows only
    # warnings. Decision lines below are print()ed directly, so the
    # console carries exactly the trade calls and the session summary.
    logger = logs.get_logger(LOGGER_NAME, quiet_console=True)
    import requests as _requests

    # Signal handlers can only be installed from the main thread. When
    # the web console runs the bot in a worker thread (stop is requested
    # via request_stop() over HTTP), registering here would crash with
    # ValueError - degrade to a no-op instead.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _request_stop)
        signal.signal(signal.SIGTERM, _request_stop)

    # The owner's PC outranks the bot: run below normal priority so the
    # decide cycle's CPU burn can never starve the desktop (2026-09-14).
    _drop_process_priority()

    # The console closing its window must not kill the market-watcher:
    # stdout goes to a pipe owned by the console, and a print to a dead
    # pipe raises BrokenPipeError and would end the session mid-market
    # (2026-09-14). Trade calls survive in the log + decisions ledger,
    # and this handler keeps the process alive through console death.
    import _thread
    _thread.excepthook = lambda *a, **k: logger.error(
        "Background thread error: %s", a[1]
    )
    sys.stdout = _ResilientStdout(sys.stdout)

    # Persistent daily entry gate - survives restarts, resets per trading day.
    gate = EntryGate(max_entries_per_day=load_max_entries_from_config())

    # Load universe.
    from psx_core import universe as _universe
    symbols = _universe.load()
    membership = _universe.check_membership()
    logger.info(
        "Universe: %d tradable symbols (%d tagged KMIALLSHR, %d "
        "Shariah-compliant, %d ETF/REIT-excluded)",
        len(symbols), membership["tagged_kmiall"],
        membership["shariah_compliant"],
        len(membership["etf_sector_excluded"]),
    )

    # The startup banner is the first thing on the console - before any
    # poll, decide cycle, or warm-up WAIT. Silence before this point
    # read as a hung process.
    _startup_banner(
        logger, gate, datetime.now(timezone.utc),
        universe_size=len(symbols),
        ignore_schedule=args.ignore_schedule,
        args=args,
    )

    http = _requests.Session()

    try:
        session_started = False
        last_decide_time = 0.0
        cap_announced = False
        breaker_announced = False
        # Watchdog state. 2026-09-11: the poller silently died for ~3.5
        # hours (10:50-14:20 PKT) - every failure went to the log files
        # only, so the console sat "healthy" while the bot was blind.
        # Now failures escalate to the console, and a decide cycle never
        # runs on a stale feed: the freshest snapshot must be recent.
        consecutive_failures = 0
        _failure_note = MAX_CONSECUTIVE_FAILURES // 2
        last_ok_epoch = time.time()
        stale_announced = False
        bookkeeping_done_date: str | None = None
        # Each refusal reason is announced at most once per session -
        # the console carries BUY/EXIT calls, not a loop commentary.
        _announced_refusals.clear()

        while True:
            now = datetime.now(timezone.utc)

            # Signal OR web-console stop file (checked every pass; the
            # poll sleeps inside this loop, so latency is ≤ one cycle).
            if _stop_or_file(logger):
                break

            # Windows: do not let the machine sleep while we trade (see
            # _disable_sleep_while_trading). Cheap, idempotent, renewed
            # every pass.
            _disable_sleep_while_trading()

            if _STOP_REQUESTED:
                logger.info("Stop requested.")
                break

            # Check market state.
            if not sessions.is_open(now) and not args.ignore_schedule:
                if session_started:
                    # Intra-day break vs true session close. Friday has
                    # two legs; the market-closed branch at the 12:00
                    # lunch used to run the END-OF-DAY bookkeeping -
                    # force-closing open positions at lunch prices and
                    # labelling outcomes hours early. Bookkeeping runs
                    # only when no further leg starts today, and only
                    # once per trading date.
                    today_date = sessions.trading_date(now).isoformat()
                    resume = sessions.next_resumption(now)
                    if resume is not None:
                        _log_only(
                            "Intra-day break - positions stay open, "
                            f"polling resumes at {resume:%H:%M} PKT.",
                            logger,
                        )
                        _announce(
                            f"Market break - bookkeeping is NOT run "
                            f"mid-day; polling resumes {resume:%H:%M} PKT."
                        )
                        nxt = sessions.next_open(now)
                        wait = (nxt.astimezone(timezone.utc) - now).total_seconds()
                        slept = 0.0
                        while slept < wait and not _stop_or_file(logger):
                            step = min(wait - slept, 30.0)
                            time.sleep(step)
                            slept += step
                        if slept < wait:
                            break  # stopped mid-wait
                        continue

                    if bookkeeping_done_date != today_date:
                        _log_only(
                            "MARKET CLOSED - end-of-session bookkeeping "
                            "(compact, outcomes, lessons) running in the "
                            "background.",
                            logger,
                        )
                        _announce(
                            "Market closed - session summary will print when "
                            "bookkeeping finishes. You can leave this window "
                            "open or close it; everything is saved."
                        )
                        logger.info("Session closed. Compacting...")
                        try:
                            before, after = storage.compact_day(today_date)
                            logger.info("Compact: %d -> %d bytes", before, after)
                        except Exception as exc:
                            logger.warning("Compact failed: %s", exc)

                        # End-of-session bookkeeping for an intraday-only
                        # book: close anything still open at the last seen
                        # price, fold the day's volume into the cross-day
                        # baselines, and refresh the (post-close)
                        # foreign-flow table.
                        _session_close_bookkeeping(logger)
                        bookkeeping_done_date = today_date

                    logger.info("Waiting for next session...")
                    session_started = False
                    cap_announced = False
                    breaker_announced = False
                    consecutive_failures = 0

                # Sleep until next open. The full wait always completes (the
                # entry cap does NOT interrupt it - the cap is about entries,
                # not about staying alive to monitor exits and reopenings).
                nxt = sessions.next_open(now)
                wait = (nxt.astimezone(timezone.utc) - now).total_seconds()
                logger.info(
                    "Market closed. Sleeping %.1f hours until %s.",
                    wait / 3600, nxt.strftime("%Y-%m-%d %H:%M PKT"),
                )
                slept = 0.0
                while slept < wait and not _stop_or_file(logger):
                    step = min(wait - slept, 30.0)
                    time.sleep(step)
                    slept += step
                if slept < wait:
                    break  # stopped mid-wait
                continue

            session_started = True

            # Collect snapshot.
            poll_start = time.monotonic()
            try:
                if args.dry_run:
                    market_data = feed.fetch_snapshot(
                        http, market="REG", timeout=args.timeout,
                        min_instruments=feed.MIN_EXPECTED_INSTRUMENTS,
                    )
                    snapshot = feed.build_universe_snapshot(
                        market_data, symbols, "REG"
                    )
                    logger.debug(
                        "Dry-run poll: %d instruments",
                        snapshot["marketInstrumentCount"],
                    )
                else:
                    snapshot = poll_once(
                        http, symbols, "REG", args.timeout,
                        feed.MIN_EXPECTED_INSTRUMENTS,
                    )
                    storage.append_snapshot(snapshot)

                    # --- Fast exit guard (v0.8.0) -----------------------
                    # Stop-loss, target and trailing checks used to run
                    # only inside decide cycles (60-180s apart). A fast
                    # fall between cycles slipped straight through:
                    # BUXL printed -5.2% intraday against a -2.0% stop
                    # (2026-09-09) - the worst loss in the ledger was
                    # enlarged by exactly this gap. Exit checking is
                    # nearly free: one dict comprehension over the fresh
                    # snapshot plus a small JSON book read - so it runs
                    # against EVERY 5-second poll. Skipped entirely while
                    # the book is flat: zero cost, zero writes. This is
                    # also what makes the console's 180s power-saving
                    # cadence safe for the money.
                    try:
                        from portfolio import Portfolio as _Portfolio

                        cfg_fast = _read_config()
                        book = _Portfolio(
                            profit_target_low=cfg_fast.get(
                                "profit_target_low", 2.0
                            ),
                            profit_target_high=cfg_fast.get(
                                "profit_target_high", 3.0
                            ),
                            max_holding_days=cfg_fast.get(
                                "max_holding_days", 1
                            ),
                            capital=cfg_fast.get("capital", 1_000_000),
                            position_size_pct=cfg_fast.get(
                                "position_size_pct", 10.0
                            ),
                            max_loss_pct=cfg_fast.get("max_loss_pct", 2.0),
                            trailing_stop_pct=cfg_fast.get(
                                "trailing_stop_pct", 1.5
                            ),
                            trailing_stop_activation_pct=cfg_fast.get(
                                "trailing_stop_activation_pct", 1.0
                            ),
                            stale_trade_minutes=cfg_fast.get(
                                "stale_trade_minutes", 45.0
                            ),
                            stale_trade_min_gain_pct=cfg_fast.get(
                                "stale_trade_min_gain_pct", 0.2
                            ),
                        )
                        if book.open_positions:
                            price_map = {
                                sym: q["price"]
                                for sym, q in (
                                    snapshot.get("quotes") or {}
                                ).items()
                                if isinstance(
                                    q.get("price"), (int, float)
                                ) and q["price"] > 0
                            }
                            current_date = sessions.trading_date(now).isoformat()
                            for pos in book.check_exits(
                                price_map, current_date
                            ):
                                _announce(
                                    "EXIT {sym} @ {price:.2f}  P&L {pnl:+.2f} "
                                    "({reason})".format(
                                        sym=pos.symbol,
                                        price=pos.exit_price or 0.0,
                                        pnl=pos.pnl or 0.0,
                                        reason=pos.exit_reason,
                                    )
                                )
                                logger.info(
                                    "FAST EXIT %s @ %.2f (%s)",
                                    pos.symbol, pos.exit_price or 0.0,
                                    pos.exit_reason,
                                )
                            # Persist the trailing-stop ratchet even when
                            # nothing exited this poll - otherwise the
                            # stop resets to flat between decide cycles.
                            book.save()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Fast exit check failed: %s", exc)

                elapsed = time.monotonic() - poll_start

                # Log poll record.
                logs.poll_record(LOGGER_NAME, {
                    "ok": True,
                    "instruments": snapshot["marketInstrumentCount"],
                    "available": snapshot["quoteAvailable"],
                    "open": snapshot["quoteOpen"],
                    "seconds": round(elapsed, 3),
                })

                # Periodic status.
                counts = storage.count_snapshots()
                total = sum(counts.values())
                if total % 12 == 0:
                    logger.info(
                        "Poll OK | %d instruments | %d/%d quotes | %d total snapshots | %.2fs",
                        snapshot["marketInstrumentCount"],
                        snapshot["quoteAvailable"],
                        snapshot["universeCount"],
                        total,
                        elapsed,
                    )

            except Exception as exc:
                elapsed = time.monotonic() - poll_start
                logger.warning("Poll failed: %s (%.2fs)", exc, elapsed)
                logs.poll_record(LOGGER_NAME, {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                consecutive_failures += 1
                if consecutive_failures == _failure_note:
                    _announce(
                        f"PROBLEM - {consecutive_failures} polls have failed; "
                        "still retrying. Decisions are paused until the "
                        "feed recovers."
                    )
                elif (
                    consecutive_failures == MAX_CONSECUTIVE_FAILURES
                    or (
                        consecutive_failures > MAX_CONSECUTIVE_FAILURES
                        and consecutive_failures % MAX_CONSECUTIVE_FAILURES == 0
                    )
                ):
                    _announce(
                        f"WARNING - {consecutive_failures} consecutive poll "
                        "failures: the bot is NOT seeing the market. Check "
                        "the network; decisions stay paused while blind."
                    )
            else:
                if consecutive_failures >= _failure_note:
                    _announce(
                        f"Recovered - feed is back after "
                        f"{consecutive_failures} failed polls."
                    )
                consecutive_failures = 0
                last_ok_epoch = time.time()
                stale_announced = False

            # Staleness guard: never decide on a dead feed. If the market
            # is open but no snapshot has landed for a while (hung poll,
            # network stall, sleeping machine), skip the decide cycle and
            # say so - a decision from a 3-hour-old market is worse than
            # no decision. Wall-clock based (not monotonic deltas) so the
            # guard still works if this loop stalls; announce-once per
            # stall, not every cycle.
            now_epoch = time.time()
            feed_age_s = now_epoch - last_ok_epoch
            if not args.dry_run and feed_age_s > 180.0:
                if not stale_announced:
                    _announce(
                        f"WARNING - no market data for "
                        f"{feed_age_s / 60:.0f} minutes. "
                        "Decisions are HELD; exits cannot be monitored "
                        "while the feed is dead."
                    )
                    stale_announced = True
                logger.warning(
                    "No snapshot for %.0fs - holding decisions until "
                    "the feed recovers.", feed_age_s,
                )
                target = poll_start + args.collect_interval
                remaining = target - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                continue

            # Periodic decide cycle. Runs whether or not the entry cap is
            # reached: run_decide always checks exits first, and reports a
            # STAND_ASIDE once the cap is full.
            decide_elapsed = time.monotonic() - last_decide_time
            if (
                not args.dry_run
                and decide_elapsed >= args.decide_interval
                and not _STOP_REQUESTED
            ):
                # Announce a reached cap once per session, not every minute.
                today = gate.today_key()
                if not gate.allows_entry(today) and not cap_announced:
                    _log_only(
                        "Daily entry cap reached ({}/{}); monitoring exits "
                        "only.".format(
                            gate.entries_today(today),
                            gate.max_entries_per_day,
                        ), logger,
                    )
                    cap_announced = True

                logger.info("Running decide cycle...")
                decision = run_decide(logger, gate=gate)
                last_decide_time = time.monotonic()

                # v4.4.3: run_decide now stamps source='live_py' on every
                # completed cycle internally, so no separate stamp here.

                if (
                    decision
                    and decision.get("action") == "STAND_ASIDE"
                    and decision.get("metadata", {}).get("gate")
                    == "daily_loss_breaker"
                    and not breaker_announced
                ):
                    # The one WAIT worth seeing: no more entries today.
                    _announce(
                        f"WAIT - {decision.get('reason')} Exits stay monitored."
                    )
                    breaker_announced = True

                if decision and decision.get("action") == "ENTER":
                    # BUY already announced inside run_decide.
                    pass
                elif decision and decision.get("action") == "STAND_ASIDE":
                    reason = str(decision.get("reason") or "")
                    # Console-visible only when it explains a real
                    # decision AND it has not been said before: the
                    # console carries BUY/EXIT calls, not a running
                    # commentary. Everything is in the log regardless.
                    logger.info("STAND_ASIDE: %s", reason)
                    if not _is_chatter(reason):
                        key = reason.split(" (")[0][:80]
                        if key not in _announced_refusals:
                            _announced_refusals.add(key)
                            _announce(f"WAIT - {reason}")

            # Wait for next poll on fixed grid.
            target = poll_start + args.collect_interval
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

    finally:
        http.close()
        logger.info("Live runner stopped.")

    return 0


# ---------------------------------------------------------------------------
# Test mode - exercise decision engine on existing data without network
# ---------------------------------------------------------------------------

def run_test(args) -> int:
    """Test the decide cycle on existing data."""
    logger = logs.get_logger(LOGGER_NAME)
    logger.info("Test mode: running decide on existing data...")
    decision = run_decide(logger)
    if decision:
        print(json.dumps(decision, indent=2, default=str))
    else:
        print("No decision produced.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PSX KMIALL Bot - live runner.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--collect-interval", type=float, default=DEFAULT_COLLECT_INTERVAL,
        help="Seconds between snapshot polls.",
    )
    parser.add_argument(
        "--decide-interval", type=float, default=DEFAULT_DECIDE_INTERVAL,
        help="Seconds between decide cycles.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--ignore-schedule", action="store_true",
        help="Run regardless of trading hours.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Collect but don't write snapshots or run decide.",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode: run decide on existing data, no network.",
    )
    return parser.parse_args(argv)


_INSTANCE_LOCK_HANDLE = None


def _acquire_instance_lock(lock_path=None) -> bool:
    """Claim exclusive right to run the live bot. False if one already runs.

    2026-09-14: two full bot stacks ran at once (a console restart
    spawned a second pair on top of the first) and the owner's CPU paid
    for both. This OS-level region lock makes a second live bot
    impossible: it is held for the process lifetime and the OS releases
    it automatically on exit or kill - no stale files, no exceptions.
    """
    global _INSTANCE_LOCK_HANDLE
    path = lock_path or (paths.DATA_DIR / "bot_instance.lock")
    try:
        handle = open(path, "a")
    except OSError:
        return False
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        handle.close()
        return False
    _INSTANCE_LOCK_HANDLE = handle
    return True


def _release_instance_lock() -> None:
    global _INSTANCE_LOCK_HANDLE
    if _INSTANCE_LOCK_HANDLE is not None:
        try:
            _INSTANCE_LOCK_HANDLE.close()
        except OSError:
            pass
        _INSTANCE_LOCK_HANDLE = None


def main(argv=None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()
    args = parse_args(argv)

    if args.test:
        return run_test(args)

    if not _acquire_instance_lock():
        print(
            "Another Sentinel bot is already running - refusing to start "
            "a second instance. Stop the running bot first (two stacks "
            "once ran at once and hammered the CPU; this lock makes that "
            "impossible).",
            flush=True,
        )
        return 3

    try:
        return run_live(args)
    except KeyboardInterrupt:
        # Force-quit path from _request_stop: exit cleanly, no traceback.
        return 130


if __name__ == "__main__":
    sys.exit(main())
