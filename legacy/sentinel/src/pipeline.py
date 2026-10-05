"""
PSX KMIALL BOT
Pipeline orchestrator - chains collect, build, features, and decide.

This is the single entry point that runs the full pipeline:

    1. Collect snapshots (if market is open)
    2. Build the intraday dataset
    3. Compute features
    4. Run the decision engine
    5. Update the portfolio

It can also run individual stages or display status.

Usage
-----
    python src/pipeline.py                     # full pipeline
    python src/pipeline.py --stage collect     # collect only
    python src/pipeline.py --stage decide      # decide only (needs features)
    python src/pipeline.py --status            # show what's on disk
    python src/pipeline.py --portfolio-status  # show portfolio state
    python src/pipeline.py --dry-run           # run without writing snapshots
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import (
    feed,
    frames,
    logs,
    paths,
    sessions,
    storage,
    universe,
)


LOGGER_NAME = "pipeline"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_logger():
    return logs.get_logger(LOGGER_NAME)


def _load_features() -> tuple:
    """Load the feature dataset. Returns (df, summary_dict)."""
    import pandas as pd
    from build_kmiall_features import load_dataset, build

    csv_path = paths.INTRADAY_CSV
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {csv_path}\n"
            "Run the full pipeline or: python src/build_intraday_dataset.py"
        )

    df = load_dataset(csv_path)
    df, summary = build(df)
    return df, summary


# ---------------------------------------------------------------------------
# Stage: Status
# ---------------------------------------------------------------------------

def stage_status() -> int:
    """Print snapshot counts, dataset info, and portfolio state."""
    paths.enable_utf8_stdout()
    counts = storage.count_snapshots()
    total = sum(counts.values())

    print("=" * 72)
    print("THE SENTINEL - STATUS")
    print("=" * 72)

    # Universe status.
    try:
        tradable = universe.load()
        membership = universe.check_membership()
        print(f"\nUniverse            : {len(tradable)} tradable symbols "
              f"(Shariah-filtered, ETF/REIT-excluded)")
        if membership["etf_sector_excluded"]:
            print(f"Excluded ETF/REITs  : {', '.join(membership['etf_sector_excluded'])}")
    except universe.UniverseError as exc:
        print(f"\nUniverse            : ERROR ({exc})")

    print(f"\nSnapshots directory : {paths.SNAPSHOT_DIR}")
    print(f"Trading dates       : {len(counts)}")
    print(f"Total snapshots     : {total:,}")

    if counts:
        print()
        print(f"  {'date':<12} {'count':>8} {'weekday':>8}")
        for date_string, count in counts.items():
            day = datetime.fromisoformat(date_string).date()
            print(f"  {date_string:<12} {count:>8,} {day.strftime('%a'):>8}")

    # Dataset status.
    print()
    if paths.INTRADAY_CSV.exists():
        size_mb = paths.INTRADAY_CSV.stat().st_size / 1e6
        print(f"Intraday dataset    : {paths.INTRADAY_CSV.name} ({size_mb:.1f} MB)")
    else:
        print("Intraday dataset    : not built")

    if paths.FEATURES_CSV.exists():
        size_mb = paths.FEATURES_CSV.stat().st_size / 1e6
        print(f"Feature dataset     : {paths.FEATURES_CSV.name} ({size_mb:.1f} MB)")
    else:
        print("Feature dataset     : not built")

    # Market status.
    now = datetime.now(timezone.utc)
    print()
    print(f"Current time (PKT)  : {sessions.to_pkt(now):%Y-%m-%d %H:%M:%S}")
    print(f"Market open         : {sessions.is_open(now)}")
    if sessions.is_open(now):
        close = sessions.leg_end(now)
        print(f"Session closes      : {close:%H:%M:%S PKT}" if close else "")
    else:
        nxt = sessions.next_open(now)
        print(f"Next open           : {nxt:%Y-%m-%d %H:%M:%S PKT}")

    # Portfolio status.
    print()
    try:
        from portfolio import Portfolio
        portfolio = Portfolio()
        summary = portfolio.summary()
        print(f"Open positions      : {summary['open_positions']}")
        print(f"Closed trades       : {summary['closed_positions']}")
        print(f"Unrealised P&L      : {summary['open_unrealised_pnl']:+.2f}")
        print(f"Realised P&L        : {summary['closed_realised_pnl']:+.2f}")
        if summary["open_symbols"]:
            print(f"Held symbols        : {', '.join(summary['open_symbols'])}")
    except Exception:
        print("Portfolio           : not initialised")

    print()
    return 0


# ---------------------------------------------------------------------------
# Stage: Collect
# ---------------------------------------------------------------------------

def stage_collect(args) -> int:
    """Run the snapshot collector."""
    from collect_kmiall_snapshots import main as collect_main
    return collect_main([
        "--interval", str(args.interval),
        "--timeout", str(args.timeout),
    ] + (
        ["--duration", str(args.collect_duration)]
        if args.collect_duration else []
    ) + (
        ["--dry-run"] if args.dry_run else []
    ))


# ---------------------------------------------------------------------------
# Stage: Build
# ---------------------------------------------------------------------------

def stage_build() -> int:
    """Build the intraday dataset from snapshots."""
    from build_intraday_dataset import main as build_main
    return build_main([])


# ---------------------------------------------------------------------------
# Stage: Features
# ---------------------------------------------------------------------------

def stage_features() -> int:
    """Compute the feature layer."""
    from build_kmiall_features import main as features_main
    return features_main([])


# ---------------------------------------------------------------------------
# Stage: Decide
# ---------------------------------------------------------------------------

def stage_decide(args) -> int:
    """Run the decision engine and update the portfolio."""
    paths.enable_utf8_stdout()
    logger = _get_logger()

    # Load config.
    config_path = paths.PROJECT_ROOT / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}

    capital = cfg.get("capital", 1_000_000)

    # Load features.
    try:
        df, feature_summary = _load_features()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    scored = int(feature_summary["scoring"]["scored_rows"])
    logger.info("Features loaded: %d scored rows", scored)

    if scored == 0:
        logger.warning("No scored rows; skipping decision.")
        return 0

    # Persistent daily entry gate, shared with the live runner.
    from entry_gate import EntryGate, load_max_entries_from_config
    gate = EntryGate(max_entries_per_day=load_max_entries_from_config(config_path))

    # Load portfolio.
    from portfolio import Portfolio
    portfolio = Portfolio(
        profit_target_low=cfg.get("profit_target_low", 2.0),
        profit_target_high=cfg.get("profit_target_high", 3.0),
        max_holding_days=cfg.get("max_holding_days", 1),
        capital=capital,
        position_size_pct=cfg.get("position_size_pct", 10.0),
        max_loss_pct=cfg.get("max_loss_pct", 2.0),
        stale_trade_minutes=cfg.get("stale_trade_minutes", 45.0),
        stale_trade_min_gain_pct=cfg.get("stale_trade_min_gain_pct", 0.2),
    )

    # Run decision engine.
    from decision_engine import DecisionEngine, DecisionConfig

    config = DecisionConfig(
        profit_target_low=portfolio.profit_target_low,
        profit_target_high=portfolio.profit_target_high,
        max_holding_days=portfolio.max_holding_days,
        min_breadth_pct=cfg.get("min_breadth_pct", 35.0),
        max_same_day_change_pct=cfg.get("max_same_day_change_pct", 6.0),
        max_price_position=cfg.get("max_price_position", 0.85),
        min_master_score=cfg.get("min_master_score", 0.55),
        min_evidence_components=cfg.get("min_evidence_components", 5),
        min_day_value=cfg.get("min_day_value", 20_000_000.0),
        circuit_breaker_change_pct=cfg.get(
            "circuit_breaker_change_pct", 9.5
        ),
        min_entry_price=cfg.get("min_entry_price", 10.0),
    )
    engine = DecisionEngine(config, capital=capital)

    # Check exits on open positions FIRST - before any entry decision.
    latest_ts = df["timestamp"].max()
    latest = df[df["timestamp"] == latest_ts]
    price_map = {}
    if "price" in latest.columns:
        price_map = dict(zip(latest["symbol"], latest["price"]))

    current_date = sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()

    exits = portfolio.check_exits(price_map, current_date)
    for pos in exits:
        logger.info(
            "EXIT %s @ %.2f, P&L %.2f (%s)",
            pos.symbol, pos.exit_price, pos.pnl, pos.exit_reason,
        )

    held = portfolio.open_symbols

    # Entry gate: report and stop once the day's entries are used up.
    entries_used = gate.entries_today(current_date)
    if not gate.allows_entry(current_date):
        from decision_engine import Decision
        decision = Decision(
            action="STAND_ASIDE",
            reason=(
                f"Daily entry limit reached "
                f"({entries_used}/{gate.max_entries_per_day})"
            ),
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata={"entries_today": entries_used},
        )
        print()
        print("=" * 72)
        print("DECISION")
        print("=" * 72)
        print(f"  Action    : {decision.action}")
        print(f"  Reason    : {decision.reason}")
        print()
        _persist_decision(decision)
        return 0

    # Data-freshness guard: manual decide against a dataset whose latest
    # row predates the current trading session must not produce entries
    # from yesterday's market.
    if "trading_date" in df.columns:
        fresh = df[df["trading_date"] == current_date]
        fresh_scored = (
            int(fresh["feature_rank_score"].notna().sum())
            if not fresh.empty else 0
        )
        if fresh_scored == 0:
            from decision_engine import Decision
            decision = Decision(
                action="STAND_ASIDE",
                reason=(
                    "No current-session data on disk "
                    f"(dataset ends {df['timestamp'].max()}). "
                    "Run the collector during market hours first."
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={"fresh_scored_rows": 0},
            )
            print()
            print("=" * 72)
            print("DECISION")
            print("=" * 72)
            print(f"  Action    : {decision.action}")
            print(f"  Reason    : {decision.reason}")
            print()
            _persist_decision(decision)
            return 0

    decision = engine.evaluate(df, held_symbols=held)

    # Print decision.
    print()
    print("=" * 72)
    print("DECISION")
    print("=" * 72)
    print(f"  Action    : {decision.action}")
    if decision.symbol:
        print(f"  Symbol    : {decision.symbol}")
        print(f"  Score     : {decision.score:.4f}" if decision.score else "")
        print(f"  Price     : Rs. {decision.price:.2f}" if decision.price else "")
        print(f"  Quantity  : {decision.quantity} shares" if decision.quantity else "")
        print(f"  Capital   : Rs. {decision.capital_alloc:,.0f}" if decision.capital_alloc else "")
        if decision.profit_target_price:
            print(f"  Target    : Rs. {decision.profit_target_price:.2f} (+{decision.profit_target_pct:.1f}%)")
    print(f"  Reason    : {decision.reason}")
    print()

    # Execute decision.
    if decision.action == "ENTER" and decision.symbol:
        entry_date = current_date

        portfolio.open_position(
            symbol=decision.symbol,
            entry_price=decision.price,
            entry_date=entry_date,
            target_price=decision.profit_target_price,
        )
        used = gate.record_entry(entry_date)
        logger.info(
            "ENTER %s @ %.2f, target %.2f, qty=%d (entry %d/%d today)",
            decision.symbol,
            decision.price,
            decision.profit_target_price,
            decision.quantity,
            used,
            gate.max_entries_per_day,
        )
        entries_used = used

    # Print portfolio summary.
    summary = portfolio.summary()
    print("=" * 72)
    print("PORTFOLIO")
    print("=" * 72)
    print(f"  Open positions     : {summary['open_positions']}")
    print(f"  Closed trades      : {summary['closed_positions']}")
    print(f"  Unrealised P&L     : {summary['open_unrealised_pnl']:+.2f}")
    print(f"  Realised P&L       : {summary['closed_realised_pnl']:+.2f}")
    print(f"  Total P&L          : {summary['total_pnl']:+.2f}")
    if summary["open_symbols"]:
        print(f"  Held               : {', '.join(summary['open_symbols'])}")
    print(f"  Entries used today : {entries_used}/{gate.max_entries_per_day}")
    print()

    _persist_decision(decision)

    return 0


def _persist_decision(decision) -> None:
    """Append one decision to logs/decisions.jsonl."""
    log_path = paths.LOGS_DIR / "decisions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            **decision.to_dict(),
        }, default=str) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PSX KMIALL Bot - pipeline orchestrator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "stage",
        nargs="?",
        choices=["collect", "build", "features", "decide", "live", "all"],
        default="all",
        help="Which pipeline stage to run.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current state and exit.",
    )
    parser.add_argument(
        "--portfolio-status", action="store_true",
        help="Show portfolio state and exit.",
    )

    # Collector options.
    parser.add_argument(
        "--interval", type=float, default=5.0,
        help="Seconds between polls (collect stage).",
    )
    parser.add_argument(
        "--collect-duration", type=float, default=None,
        help="Max seconds for the collect stage.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Collect but don't write snapshots.",
    )

    return parser.parse_args(argv)


def run_full_pipeline(args) -> int:
    """Run all stages in sequence."""
    logger = _get_logger()
    results = {}

    # Stage 1: Collect.
    now = datetime.now(timezone.utc)
    if sessions.is_open(now) or args.dry_run:
        logger.info("Stage 1/4: Collect")
        results["collect"] = stage_collect(args)
    else:
        logger.info("Stage 1/4: Collect - market closed, skipping")
        results["collect"] = 0

    # Stage 2: Build dataset.
    logger.info("Stage 2/4: Build dataset")
    results["build"] = stage_build()

    # Stage 3: Compute features.
    logger.info("Stage 3/4: Features")
    results["features"] = stage_features()

    # Stage 4: Decide.
    logger.info("Stage 4/4: Decide")
    results["decide"] = stage_decide(args)

    # Summary.
    failures = [k for k, v in results.items() if v != 0]
    if failures:
        logger.error("Pipeline completed with failures: %s", ", ".join(failures))
        return 1

    logger.info("Pipeline completed successfully.")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    paths.ensure_dirs()

    if args.status:
        return stage_status()

    if args.portfolio_status:
        from portfolio import Portfolio
        portfolio = Portfolio()
        summary = portfolio.summary()
        print(json.dumps(summary, indent=2))
        return 0

    if args.stage == "all":
        return run_full_pipeline(args)

    if args.stage == "live":
        from live import main as live_main
        return live_main()

    stage_map = {
        "collect": lambda: stage_collect(args),
        "build": stage_build,
        "features": stage_features,
        "decide": lambda: stage_decide(args),
    }

    return stage_map[args.stage]()


if __name__ == "__main__":
    sys.exit(main())
