"""Cloud-only replay of the actual intraday scanner, never daily-bar proxies.

Input: archived tape_bars_*.ndjson files written by src.data.tape_bars.
Output: JSON per-session evidence, costs, fixed chronological holdout and
measured replay timing. Synthetic fixtures never count as strategy results.
Asia/Karachi (UTC+5), no network, no signal delivery and no shared claims.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest


def main(argv=None) -> int:
    guard_cloud_backtest("scripts/backtest_smc.py")
    import argparse
    import hashlib
    import json
    import time
    from collections import defaultdict
    from datetime import datetime, timedelta

    from scripts.intraday_pipeline import load_kmiall, monitor_exit, session_close_price
    from src import config
    from src.data.sessions import KARACHI
    from src.signals import momentum_scanner as scanner
    from src.signals.trade_state import SessionState

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    universe = load_kmiall()
    days = defaultdict(lambda: defaultdict(dict))
    provenance = []
    conflicts = set()
    for path in sorted(args.input.rglob("tape_bars_*.ndjson")):
        raw = path.read_bytes()
        provenance.append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest()})
        for line in raw.decode("utf-8").splitlines():
            row = json.loads(line)
            symbol = row["symbol"]
            if symbol not in universe:
                continue
            stamp = datetime.fromisoformat(row["ts"])
            if stamp.tzinfo is None:
                raise ValueError(f"archive minute has no timezone: {path.name}")
            stamp = stamp.astimezone(KARACHI)
            bar = scanner.MinuteBar(stamp, *(float(row[k]) for k in ("o", "h", "l", "c")),
                                     float(row["v"]))
            old = days[stamp.date()][symbol].get(stamp)
            if old is not None and old != bar:
                conflicts.add(stamp.date())
            days[stamp.date()][symbol][stamp] = bar
    started = time.monotonic()
    sessions = []
    scans = 0
    for day, symbols in sorted(days.items()):
        state = SessionState(day.isoformat())
        state.begin_session()
        bars = {symbol: sorted(values.values(), key=lambda b: b.timestamp)
                for symbol, values in symbols.items()}
        moments = sorted({b.timestamp + timedelta(minutes=1) for values in bars.values() for b in values})
        last_session = None
        eligible_scans = 0
        for moment in moments:
            prefix = {s: [b for b in values if b.timestamp + timedelta(minutes=1) <= moment]
                      for s, values in bars.items()}
            prefix = {s: values for s, values in prefix.items() if values}
            session = scanner.SessionData(day, moment, prefix, True,
                                          sum(map(len, prefix.values())), 0, 0,
                                          source="archived broker tape minute bars")
            last_session = session
            if state.in_position():
                monitor_exit(state, session)
            if state.trade_taken:
                continue
            quality = scanner.assess_quality(session, universe)
            scans += 1
            if quality.status != "OK" or day in conflicts:
                continue
            eligible_scans += 1
            result = scanner.select_one(session, quality)
            if result.candidate:
                pick = result.candidate
                state.enter(pick["symbol"], pick["price"]["last"], moment,
                            pick["score"], stop_loss=pick["stop_loss"])
        final_price = session_close_price(last_session, state.symbol) if last_session else None
        if state.in_position() and final_price is not None:
            state.close_day(final_price, last_session.as_of)
        unresolved = state.trade_taken and state.exit_price is None
        gross = state.return_pct if state.trade_taken and not unresolved else None
        sessions.append({**state.session_record(), "gross_return": gross,
                         "net_return": config.net_return(gross),
                         "eligible_scans": eligible_scans,
                         "quality": "CONFLICT" if day in conflicts else
                                    "UNRESOLVED" if unresolved else
                                    "SCANNABLE" if eligible_scans else "DATA_BLOCKED"})
    cut = max(1, len(sessions) * 2 // 3)

    def metrics(rows):
        traded = [r for r in rows if r["net_return"] is not None]
        returns = [r["net_return"] for r in traded]
        wins = sum(v > 0 for v in returns)
        gains = sum(v for v in returns if v > 0)
        losses = -sum(v for v in returns if v < 0)
        return {"sessions": len(rows), "trades": len(traded),
                "target_hits": sum(r["target_hit"] for r in traded),
                "net_win_rate": wins / len(returns) if returns else None,
                "net_expectancy": sum(returns) / len(returns) if returns else None,
                "profit_factor": gains / losses if losses else None,
                "unresolved": sum(r["quality"] == "UNRESOLVED" for r in rows)}

    report = {"strategy": config.SCANNER_VERSION, "provenance": provenance,
              "universe": "current KMIALL snapshot, not historical membership",
              "timing_seconds": time.monotonic() - started, "scan_count": scans,
              "target": "2% gross paper reference, costs deducted separately",
              "cost_model": {"side_bps": config.COST_SIDE_BPS,
                             "slippage_bps": config.SLIPPAGE_SIDE_BPS,
                             "cgt": config.CGT_RATE},
              "parameters": config.config_snapshot()["smc"],
              "split": "first two-thirds dates descriptive, final third untouched holdout; no tuning",
              "all": metrics(sessions), "development": metrics(sessions[:cut]),
              "holdout": metrics(sessions[cut:]), "sessions": sessions,
              "profitable_strategy_established": False,
              "evidence": "bounded historical replay, not the prospective frozen production gate"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("strategy", "all", "holdout", "timing_seconds")}, indent=2))
    if not provenance or not days:
        print("No real archived minute bars available; no performance result manufactured.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
