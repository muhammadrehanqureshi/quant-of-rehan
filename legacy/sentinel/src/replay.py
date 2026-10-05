"""
PSX KMIALL BOT
Replay - the walk-forward backtest harness.

Why this exists
---------------
The live bot learns from roughly three executed trades per day, which
makes every threshold (breadth floor, conviction gate, strong-horse
margins) a matter of faith for months. The snapshot archive already
holds the alternative: every 5-second poll of every symbol. This
harness re-decides that history through the CURRENT engine and prices
every would-have-been trade against what actually happened next -
hundreds of virtual trades where live produced a handful, without
waiting and without risking anything.

The one law: WALK-FORWARD. A decision at time T may only read snapshots
with timestamp <= T and regime histories with sessions < T's date.
Both are enforced structurally (slicing + truncation), not by trust:

  * dataset: the step's frame is sliced to timestamps <= T before the
    feature transforms run - exactly what the live bot saw when its
    rebuilt dataset still ended at T;
  * regime context: market_regime.load_context(as_of=T's date)
    truncates index, foreign-flow and daily-close histories to sessions
    strictly before the replay date.

Decisions mimic the live cadence (one per DECIDE_INTERVAL_S seconds of
snapshot time) and virtual trades exit by the same rules as the live
book - hard stop, trailing stop, target, or the last seen price of the
session (intraday-only book) - minus a round-trip costs haircut so a
1.5% scalper is not flattered by friction-free fills.

CLI:
    python src/replay.py --date 2026-09-09          # one session
    python src/replay.py --from 2026-09-04          # every stored session
    python src/replay.py --date 2026-09-09 --json   # machine-readable
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths

DECIDE_INTERVAL_S = 60.0
COSTS_PCT = 0.10  # round-trip commission + levies haircut per trade


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class ReplayTrade:
    symbol: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    score: float
    exit_kind: str  # target | stop | trail | time
    pnl_pct: float
    # Entry-time context, recorded so win/loss separation can be mined
    # across every virtual trade the engine ever considers (not just
    # the ones a 3/day cap let through live).
    breadth_pct: float | None = None
    market_vw_change_pct: float | None = None
    market_off_low_pct: float | None = None
    change_pct: float | None = None
    vwap_ratio: float | None = None
    relative_volume_1m: float | None = None
    momentum_1m_pct: float | None = None
    evidence_count: int | None = None
    strong_horse: bool = False
    recovery_mode: bool = False


@dataclass
class ReplayReport:
    """One session's replay verdict - the printed and --json artifact."""

    trading_date: str
    snapshots: int = 0
    decisions: int = 0
    enters: int = 0
    stands_aside: int = 0
    engine_errors: int = 0
    trades: list[ReplayTrade] = field(default_factory=list)
    # Every best-candidate ENTER the engine considered, priced through
    # the same exit rules regardless of the book's cap - the raw menu
    # the win/loss study learns from.
    mined_trades: list[ReplayTrade] = field(default_factory=list)
    stand_aside_reasons: dict[str, int] = field(default_factory=dict)
    regime_data_stale: bool = False

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl_pct > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl_pct <= 0)

    @property
    def win_rate(self) -> float | None:
        return self.wins / len(self.trades) if self.trades else None

    @property
    def avg_pnl_pct(self) -> float | None:
        if not self.trades:
            return None
        return sum(t.pnl_pct for t in self.trades) / len(self.trades)

    def to_dict(self) -> dict:
        return {
            "trading_date": self.trading_date,
            "snapshots": self.snapshots,
            "decisions": self.decisions,
            "enters": self.enters,
            "stands_aside": self.stands_aside,
            "engine_errors": self.engine_errors,
            "stand_aside_reasons": self.stand_aside_reasons,
            "regime_data_stale": self.regime_data_stale,
            "trades": [vars(t) for t in self.trades],
            "mined_trades": [vars(t) for t in self.mined_trades],
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "avg_pnl_pct": self.avg_pnl_pct,
            "costs_pct_per_trade": COSTS_PCT,
        }

    def summary_line(self) -> str:
        wr = f"{self.win_rate:.0%}" if self.win_rate is not None else "n/a"
        avg = (
            f"{self.avg_pnl_pct:+.2f}%"
            if self.avg_pnl_pct is not None
            else "n/a"
        )
        return (
            f"{self.snapshots:,} snapshots, {self.decisions} decisions -> "
            f"{self.enters} enters ({self.wins}W/{self.losses}L, "
            f"win rate {wr}, avg {avg} after costs)"
            + (
                f", {self.engine_errors} ENGINE ERRORS"
                if self.engine_errors
                else ""
            )
        )


# ---------------------------------------------------------------------------
# Pricing a virtual trade
# ---------------------------------------------------------------------------


def exit_reason_at(
    entry_price: float,
    prices: list[tuple[datetime, float]],
    *,
    max_loss_pct: float,
    trailing_stop_pct: float,
    trailing_activation_pct: float,
    profit_target_pct: float,
    entered_at: datetime | None = None,
    stale_min: float = 0.0,
    stale_min_gain_pct: float = 0.2,
    high_prices: list[tuple[datetime, float]] | None = None,
) -> tuple[datetime, float, str] | None:
    """
    Walk a virtual position forward tick by tick and return
    (exit_time, exit_price, kind) at the first rule touch, or the last
    seen price when the series ends (intraday book: forced flat at
    close). None when no price exists after the entry (suspended all
    session, data hole).

    Same priority as the live book: stop/trail before target.

    entered_at: ticks strictly BEFORE this instant are skipped. Without
    the cutoff the walk began at the day's first print, so pre-entry
    (lower, since the engine buys strength) prices could fire the
    virtual stop or target - exits attributed to times before the
    position existed (surfaced 2026-09-12: exits stamped 04:18 for a
    10:15 entry).
    """
    last_ts: datetime | None = None
    last_price: float | None = None

    stop = entry_price * (1.0 - max_loss_pct / 100.0)
    trail_stop: float | None = None
    best = entry_price
    gate_px = entry_price * (1.0 + stale_min_gain_pct / 100.0)

    # v0.20.3 touch capture (mirrors the live book's Rule 3-touch): a
    # limit order fills on a TOUCH, so a target printed between polls
    # is a real fill. The snapshots carry each poll's session high, so
    # the walk sees exactly what the live book sees. Attribution (the
    # STL lesson): the seed is the session high on the ENTRY snapshot
    # (the strongest pre-holding print) - only a LATER poll's high
    # proves the touch happened while we held. Missing highs -> walk
    # behaves exactly as before (the replay never invents fills).
    target = entry_price * (1.0 + profit_target_pct / 100.0)
    touch_ts: datetime | None = None
    if high_prices and entered_at is not None:
        seed_pair = next(
            (
                (ts, h)
                for ts, h in reversed(high_prices)
                if ts <= entered_at
            ),
            None,
        )
        # The seed must be the entry snapshot itself (or the one poll
        # immediately before it, if that snapshot lacked the high) -
        # an older seed could hide a pre-entry spike and fake a touch.
        if (
            seed_pair is not None
            and (entered_at - seed_pair[0]).total_seconds() <= 960.0
        ):
            seed = seed_pair[1]
            if seed is not None and seed < target:
                touch_ts = next(
                    (
                        ts
                        for ts, h in high_prices
                        if ts > entered_at and h >= target
                    ),
                    None,
                )

    for ts, price in prices:
        if entered_at is not None and ts < entered_at:
            continue
        last_ts, last_price = ts, price
        if touch_ts is not None and touch_ts <= ts:
            # The session high crossed the target at a moment the
            # polls never sampled - a resting limit would have filled.
            return touch_ts, target, "target"
        best = max(best, price)
        if best >= entry_price * (1.0 + trailing_activation_pct / 100.0):
            trail_stop = best * (1.0 - trailing_stop_pct / 100.0)
        effective_stop = max(stop, trail_stop) if trail_stop else stop
        if price <= effective_stop:
            return ts, price, "trail" if trail_stop else "stop"
        if price >= target:
            return ts, price, "target"
        # Stale-trade timeout (v0.9.0): no meaningful gain inside the
        # window -> exit at market. Mirrors the live book's Rule S.
        if (
            stale_min > 0
            and entered_at is not None
            and (ts - entered_at).total_seconds() >= stale_min * 60.0
            and price < gate_px
        ):
            return ts, price, "stale"

    if last_ts is None or last_price is None:
        return None
    return last_ts, last_price, "time"


# ---------------------------------------------------------------------------
# Session reading
# ---------------------------------------------------------------------------


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def iter_day_rows(
    date: str,
    symbols: list[str],
    *,
    quote_to_row,
    empty_quote: dict,
    snapshot_dir: Path | None = None,
):
    """
    Yield (timestamp, rows) per stored snapshot, ascending, rows being
    the flat per-symbol dicts load_rows would produce (quote_to_row for
    present quotes, empty_quote for absent ones) - the replay reads the
    archive exactly the way the dataset builder reads it.
    """
    snapshot_dir = snapshot_dir or paths.SNAPSHOT_DIR
    path = snapshot_dir / f"{date}.jsonl.gz"
    if not path.exists():  # legacy uncompressed layout
        path = snapshot_dir / f"{date}.jsonl"
        if not path.exists():
            return

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snapshot = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(snapshot.get("generatedAt"))
            if ts is None:
                continue
            quotes = snapshot.get("quotes")
            if not isinstance(quotes, dict):
                quotes = {}

            rows = []
            for symbol in symbols:
                quote = quotes.get(symbol)
                base = {
                    "timestamp": ts,
                    "symbol": symbol,
                    "quote_available": quote is not None,
                }
                if quote is None:
                    rows.append({**base, **empty_quote})
                else:
                    rows.append({**base, **quote_to_row(quote)})
            yield ts, rows


def stored_dates(snapshot_dir: Path | None = None) -> list[str]:
    """Every trading date with a stored snapshot file, oldest first."""
    snapshot_dir = snapshot_dir or paths.SNAPSHOT_DIR
    dates = []
    for path in snapshot_dir.glob("*.jsonl.gz"):
        name = path.name
        # Fixed-width YYYY-MM-DD prefix; Path.stem would leave a
        # ".jsonl" tail ("2026-09-04.jsonl" for "2026-09-04.jsonl.gz").
        if len(name) >= 10 and name[:4].isdigit():
            dates.append(name[:10])
    return sorted(dates)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def replay_date(
    date: str,
    config: dict | None = None,
    *,
    quiet: bool = False,
    decide_interval_s: float = DECIDE_INTERVAL_S,
    until_pkt: int | None = None,
    after_pkt: int | None = None,
) -> ReplayReport:
    """
    Walk one stored session and price every decision the current engine
    would have made, walk-forward at the decide cadence.

    decide_interval_s: seconds of snapshot time between decisions. The
    live cadence (60s) is the default; a coarser interval (300s+) is a
    fast first-pass for parameter sweeps - every gate still runs, the
    grid just samples it less often.
    """
    config = config or _read_config()

    import build_intraday_dataset as intraday_builder
    import build_kmiall_features as features_builder
    import decision_engine as decision_engine_mod
    import market_regime as market_regime_mod
    from psx_core import universe as universe_mod

    symbols = universe_mod.load()

    report = ReplayReport(trading_date=date)

    # --- Read the session ONCE into one flat frame ------------------------
    # (The per-step cost is then a vectorised timestamp mask + the same
    # transform passes the live bot runs each decide cycle.)
    all_rows: list[dict] = []
    for ts, rows in iter_day_rows(
        date,
        symbols,
        quote_to_row=intraday_builder.quote_to_row,
        empty_quote=intraday_builder._EMPTY_QUOTE,
    ):
        report.snapshots += 1
        all_rows.extend(rows)
    if not all_rows:
        return report

    base = pd.DataFrame(all_rows)
    del all_rows
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)
    # Sort FIRST, then take the ts column: the per-step mask below is
    # applied positionally to this exact frame. A mask built from an
    # unsorted column and applied to a sorted frame aligned rows with
    # the wrong timestamps (silent data corruption in the walk-forward
    # slice - every feature and decision computed over a Frankenstein
    # mix of times).
    base_sorted = base.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    ts_col = base_sorted["timestamp"]

    # Per-symbol close series for exit pricing (plus the session-high
    # series so the exit walk can see touches between polls - the same
    # cure the live book got in v0.20.3).
    series: dict[str, list[tuple[datetime, float]]] = {}
    high_series: dict[str, list[tuple[datetime, float]]] = {}
    priced = base[["symbol", "timestamp", "price", "high"]].dropna(
        subset=["symbol", "timestamp", "price"]
    )
    priced = priced[priced["price"] > 0]
    for symbol, group in priced.groupby("symbol", sort=False):
        series[symbol] = list(
            zip(group["timestamp"], group["price"].astype(float))
        )
        series[symbol].sort(key=lambda p: p[0])
        highs = group[group["high"].notna() & (group["high"] > 0)]
        high_series[symbol] = sorted(
            zip(highs["timestamp"], highs["high"].astype(float)),
            key=lambda p: p[0],
        )

    # --- Engine configured exactly as live configures it ------------------
    dcfg = decision_engine_mod.DecisionConfig(
        min_breadth_pct=config.get("min_breadth_pct", 40.0),
        max_same_day_change_pct=config.get("max_same_day_change_pct", 4.0),
        max_price_position=config.get("max_price_position", 0.75),
        min_master_score=config.get("min_master_score", 0.55),
        min_evidence_components=config.get("min_evidence_components", 5),
        min_day_value=config.get("min_day_value", 5_000_000.0),
        circuit_breaker_change_pct=config.get("circuit_breaker_change_pct", 9.5),
        min_entry_price=config.get("min_entry_price", 10.0),
        trend_filter_enabled=config.get("trend_filter_enabled", True),
        require_above_vwap=config.get("require_above_vwap", True),
        index_regime_enabled=config.get("index_regime_enabled", True),
        index_sma_window=config.get("index_sma_window", 20),
        regime_data_veto_enabled=config.get("regime_data_veto_enabled", True),
        max_breadth_drop_pct=config.get("max_breadth_drop_pct", 10.0),
        opening_hold_minutes=config.get("opening_hold_minutes", 15),
        sniper_window_end_minutes=config.get(
            "sniper_window_end_minutes", 35
        ),
        sector_guard_enabled=config.get("sector_guard_enabled", True),
        max_multi_day_gain_pct=config.get("max_multi_day_gain_pct", 15.0),
        strong_horse_enabled=config.get("strong_horse_enabled", True),
        strong_horse_min_outperformance_pct=config.get(
            "strong_horse_min_outperformance_pct", 3.0
        ),
        strong_horse_min_score=config.get("strong_horse_min_score", 0.62),
        strong_horse_max_same_day_change_pct=config.get(
            "strong_horse_max_same_day_change_pct", 9.0
        ),
        foreign_flow_regime_enabled=config.get(
            "foreign_flow_regime_enabled", True
        ),
        foreign_flow_streak_days=config.get("foreign_flow_streak_days", 3),
        foreign_flow_min_net_usd=config.get(
            "foreign_flow_min_net_usd", -5_000_000.0
        ),
        institutional_flow_enabled=config.get(
            "institutional_flow_enabled", True
        ),
        institutional_war_divergence=config.get(
            "institutional_war_divergence", 2.0
        ),
        institutional_fomo_ratio=config.get(
            "institutional_fomo_ratio", 1.35
        ),
        confirmation_enabled=config.get("confirmation_enabled", True),
        confirmation_at_high_pct=config.get(
            "confirmation_at_high_pct", 1.5
        ),
        confirmation_fresh_minutes=config.get(
            "confirmation_fresh_minutes", 20.0
        ),
        recovery_breadth_pct=config.get("recovery_breadth_pct", 55.0),
        money_tape_recovery_enabled=config.get(
            "money_tape_recovery_enabled", True
        ),
        money_tape_min_vw_change_pct=config.get(
            "money_tape_min_vw_change_pct", 0.0
        ),
        money_tape_min_slope_30m=config.get("money_tape_min_slope_30m", 1.0),
        recovery_mode_enabled=config.get("recovery_mode_enabled", True),
        recovery_min_off_low_pct=config.get(
            "recovery_min_off_low_pct", 3.0
        ),
        recovery_breadth_arm_pct=config.get(
            "recovery_breadth_arm_pct", 70.0
        ),
        recovery_slope_30m=config.get("recovery_slope_30m", 3.0),
        recovery_max_day_change_pct=config.get(
            "recovery_max_day_change_pct", 8.0
        ),
        recovery_recent_high_minutes=config.get(
            "recovery_recent_high_minutes", 45.0
        ),
        recovery_rise_lookback_minutes=config.get(
            "recovery_rise_lookback_minutes", 15.0
        ),
        min_sector_money_flow=config.get("min_sector_money_flow", 0.70),
        min_bid_ask_balance=config.get("min_bid_ask_balance", 0.50),
        hard_min_breadth_pct=config.get("hard_min_breadth_pct", 35.0),
        require_positive_day_change=config.get(
            "require_positive_day_change", True
        ),
        max_entry_off_low_pct=config.get("max_entry_off_low_pct", 3.0),
        recovery_max_entry_off_low_pct=config.get(
            "recovery_max_entry_off_low_pct", 6.0
        ),
    )

    max_loss_pct = float(config.get("max_loss_pct", 1.5))
    trail_pct = float(config.get("trailing_stop_pct", 1.5))
    trail_act = float(config.get("trailing_stop_activation_pct", 1.0))
    target_pct = float(config.get("profit_target_low", 0.5))
    stale_min = float(config.get("stale_trade_minutes", 45.0))
    stale_gain = float(config.get("stale_trade_min_gain_pct", 0.2))

    frames_mod = intraday_builder
    fmod = features_builder

    step_start: datetime | None = None
    open_symbols: set[str] = set()
    max_entries = int(config.get("max_entries_per_day", 3))
    for decision_time in _decide_grid(ts_col, decide_interval_s):
        # --until HH:MM: the decision window ends here; exits for
        # entries already priced still walk the full day afterwards.
        # The frame's timestamps are PKT wall-clock (labeled UTC), so
        # no offset is applied.
        if until_pkt is not None and (
            decision_time.hour * 60 + decision_time.minute
        ) > until_pkt:
            break
        # --after HH:MM: skip decisions before this PKT time (exits for
        # entries priced still walk the full day afterwards).
        if after_pkt is not None and (
            decision_time.hour * 60 + decision_time.minute
        ) < after_pkt:
            continue
        # --- Walk-forward slice: only what a live rebuild at this moment
        # could have seen (snapshots up to and including now).
        mask = ts_col <= decision_time
        if not mask.any():
            continue
        df = base_sorted[mask.values].copy()
        if df.empty:
            continue

        try:
            df = _transform_dataset(df, frames_mod, fmod)
        except Exception as exc:  # noqa: BLE001
            if not quiet:
                print(f"    step {decision_time:%H:%M:%S} build failed: {exc}")
            continue

        report.decisions += 1

        try:
            ctx = market_regime_mod.load_context(config, as_of=date)
            if getattr(ctx, "index_history_stale", False):
                report.regime_data_stale = True
        except Exception:  # noqa: BLE001
            ctx = None

        # v2.1.1 Rule 11c in replay: stored snapshots predate the
        # index-quote capture, so the gate's historical input is the
        # value-weighted money lens of the open cross-section AT THIS
        # timestamp (inside the walk-forward slice - no look-ahead).
        # Badged PROXY in the context; the live path uses the real page
        # quote instead.
        if ctx is not None and "market_vw_change_pct" in df.columns:
            _step_rows = df.loc[
                df["timestamp"] == decision_time, "market_vw_change_pct"
            ]
            if len(_step_rows):
                market_regime_mod.apply_index_proxy(
                    ctx, _step_rows.iloc[-1]
                )

        engine = decision_engine_mod.DecisionEngine(dcfg)
        try:
            decision = engine.evaluate(df, held_symbols=set(open_symbols), context=ctx)
            _last_trace = getattr(engine, "_last_filter_trace", None)
        except Exception as exc:  # noqa: BLE001
            # One malformed step must never kill the session's evidence:
            # count it, surface it, keep walking.
            report.engine_errors += 1
            if not quiet:
                print(
                    f"    step {decision_time:%H:%M:%S} "
                    f"engine error: {type(exc).__name__}: {exc}"
                )
            continue

        if decision.action != "ENTER" or not decision.symbol:
            report.stands_aside += 1
            key = (decision.reason or "unknown").split(" (")[0][:80]
            report.stand_aside_reasons[key] = (
                report.stand_aside_reasons.get(key, 0) + 1
            )
            continue

        # --- Mine the best candidate even when the book is full ---------
        # The cap and held-symbol exclusions stop the BOOK from taking
        # the trade, not the EVIDENCE from being priced. Every best-
        # candidate ENTER gets its outcome walked, cap or not - the
        # win/loss study needs the engine's full menu, not the days the
        # cap happened to close early.
        best = decision.symbol

        # --- Entry-time context snapshot for the ledger ----------------
        best_row = None
        try:
            latest_slice = df[df["timestamp"] == df["timestamp"].max()]
            match = latest_slice[latest_slice["symbol"] == best]
            if not match.empty:
                best_row = match.iloc[0]
        except Exception:  # noqa: BLE001 - context is optional
            best_row = None

        def _num(column: str) -> float | None:
            if best_row is None or column not in best_row.index:
                return None
            value = best_row[column]
            try:
                return None if pd.isna(value) else float(value)
            except (TypeError, ValueError):
                return None

        def _walk_trade() -> ReplayTrade | None:
            entry_price = float(decision.price)
            result = exit_reason_at(
                entry_price,
                series.get(decision.symbol, []),
                max_loss_pct=max_loss_pct,
                trailing_stop_pct=trail_pct,
                trailing_activation_pct=trail_act,
                profit_target_pct=target_pct,
                entered_at=decision_time,
                stale_min=stale_min,
                stale_min_gain_pct=stale_gain,
                high_prices=high_series.get(decision.symbol),
            )
            if result is None:
                return None
            exit_time, exit_price, kind = result
            gross = (exit_price / entry_price - 1.0) * 100.0
            meta = decision.metadata or {}
            regime = meta.get("regime") or {}
            return ReplayTrade(
                symbol=decision.symbol,
                entry_time=decision_time.isoformat(),
                entry_price=entry_price,
                exit_time=exit_time.isoformat(),
                exit_price=exit_price,
                score=float(decision.score or 0.0),
                exit_kind=kind,
                pnl_pct=round(gross - COSTS_PCT, 4),
                breadth_pct=_num("breadth_pct"),
                market_vw_change_pct=_num("market_vw_change_pct"),
                market_off_low_pct=_num("market_off_low_pct"),
                change_pct=_num("change_pct"),
                vwap_ratio=_num("vwap_ratio"),
                relative_volume_1m=_num("relative_volume_1m"),
                momentum_1m_pct=_num("momentum_1m_pct"),
                evidence_count=(
                    int(meta["evidence_count"])
                    if meta.get("evidence_count") is not None else None
                ),
                strong_horse=bool(meta.get("strong_horse")),
                recovery_mode=bool(regime.get("money_tape_recovery")),
            )

        # Price the evidence no matter what the book does.
        mined = _walk_trade()
        if mined is not None:
            report.mined_trades.append(mined)

        # Mirror the live book: one position per symbol (correlation
        # guard needs held symbols to mean anything) and the same daily
        # entry cap. Without these the replay shows an unrealistically
        # busy book (2026-09-12: GTYR/HUBC entered twice in 7 minutes).
        if len(open_symbols) >= max_entries:
            continue
        open_symbols.add(decision.symbol)

        if mined is not None:
            report.enters += 1
            report.trades.append(mined)

    if step_start is None:  # pragma: no cover - guard, never hit
        pass
    return report


def _decide_grid(ts_col: pd.Series, interval_s: float = DECIDE_INTERVAL_S) -> list[datetime]:
    """
    The decide cadence in snapshot time: the first timestamp, then every
    interval_s later that has data - mirroring the live loop's fixed
    interval on a stream that arrives in bursts.
    """
    times = sorted(ts_col.unique())
    if not times:
        return []
    grid = []
    next_t = pd.Timestamp(times[0])
    step = pd.Timedelta(seconds=interval_s)
    for t in times:
        t = pd.Timestamp(t)
        if t >= next_t:
            grid.append(t.to_pydatetime())
            next_t = t + step
    return grid


def _transform_dataset(df, frames_mod, fmod):
    """The dataset builder's exact transform pipeline on a raw slice."""
    # add_session_columns lives in psx_core.frames, which the builder
    # imports as `frames` - reach it through the builder module.
    df = frames_mod.frames.add_session_columns(df)
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    df["price_valid"] = df["price"].notna() & (df["price"] > 0)
    df = frames_mod.add_price_position_features(df)
    df = frames_mod.add_sequential_features(df)
    df = frames_mod.add_windowed_features(df)
    df = frames_mod.add_relative_volume(df)
    df = frames_mod.add_liquidity_features(df)
    df = frames_mod.add_usability_flags(df)
    df = frames_mod.add_breadth(df)
    df = df[[c for c in frames_mod.COLUMNS if c in df.columns]]
    df = fmod.coerce_dtypes(df)
    df, summary = fmod.build(df)
    if int(summary["scoring"]["scored_rows"]) == 0:
        raise ValueError("no scored rows at this step")
    return df


def _read_config() -> dict:
    try:
        return json.loads(
            (paths.PROJECT_ROOT / "config.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Walk-forward replay of stored sessions through the "
        "current decision engine."
    )
    parser.add_argument("--date", help="single trading date (YYYY-MM-DD)")
    parser.add_argument(
        "--from",
        dest="from_date",
        help="replay every stored session from this date on",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DECIDE_INTERVAL_S,
        help="seconds of snapshot time between decisions (default 60; "
        "use 300+ for fast parameter sweeps)",
    )
    parser.add_argument(
        "--until",
        dest="until_pkt",
        metavar="HH:MM",
        default=None,
        help="stop deciding at this PKT time (exits still walk the full "
        "day). Splits a big session into two affordable runs.",
    )
    parser.add_argument(
        "--after",
        dest="after_pkt",
        metavar="HH:MM",
        default=None,
        help="skip decisions before this PKT time (exits still walk the "
        "full day). Splits a big session into two affordable runs.",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    until_pkt = None
    after_pkt = None
    if args.until_pkt:
        hh, mm = (int(p) for p in args.until_pkt.split(":"))
        until_pkt = hh * 60 + mm  # minutes since PKT midnight
    if args.after_pkt:
        hh, mm = (int(p) for p in args.after_pkt.split(":"))
        after_pkt = hh * 60 + mm  # minutes since PKT midnight

    paths.ensure_dirs()

    if args.date:
        dates = [args.date]
    elif args.from_date:
        dates = [d for d in stored_dates() if d >= args.from_date]
    else:
        dates = stored_dates()
    if not dates:
        print("No stored sessions found in data/snapshots/.")
        return 1

    reports = []
    for date in dates:
        print(f"\n=== {date} ===", flush=True)
        report = replay_date(
            date,
            quiet=False,
            decide_interval_s=args.interval,
            until_pkt=until_pkt,
            after_pkt=after_pkt,
        )
        reports.append(report)
        print("  " + report.summary_line())
        for kind in ("target", "trail", "stop", "time"):
            n = sum(1 for t in report.trades if t.exit_kind == kind)
            if n:
                print(f"    {kind:6s} x{n}")
        for reason, n in sorted(
            report.stand_aside_reasons.items(),
            key=lambda kv: -kv[1],
        )[:5]:
            print(f"    stand-aside x{n}: {reason}")
        if report.regime_data_stale:
            print("    regime data was stale for part of this session")

    if len(reports) > 1:
        trades = [t for r in reports for t in r.trades]
        print("\n=== COMBINED ===")
        if trades:
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            total = sum(t.pnl_pct for t in trades)
            print(
                f"{len(reports)} sessions, {len(trades)} virtual trades, "
                f"{wins}W/{len(trades) - wins}L "
                f"(win rate {wins / len(trades):.0%}), "
                f"total {total:+.2f}%, avg {total / len(trades):+.2f}%"
            )
        else:
            print(f"{len(reports)} sessions, 0 virtual trades")

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
