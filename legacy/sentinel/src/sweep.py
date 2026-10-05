"""The rule sweeper: thresholds chosen by data, not by hand.

Every number in the current rulebook (0.55 conviction, the 35% floor,
the chase caps) was hand-picked from ~9-11 labeled trades. This module
replaces that practice:

  CAPTURE  (--capture [--date D])  Walk each stored session at the
      decide cadence; at every step record the best tradable candidate
      and its FULL FORWARD PRICE PATH, with all gate inputs as plain
      numbers. Gate VALUES are captured, never applied - the sweep owns
      every threshold. One capture per session; any rulebook can then
      be evaluated against it forever.

  EVALUATE (--evaluate)            Grid-search every rulebook over all
      captured panels. Each simulation is honest: market gates in
      engine order, a one-position book (no re-entry while held, 3
      entries/day, the slot frees at the position's EXIT time), exits
      walked on the stored path, and the OWNER'S REAL FEE STACK
      deducted per trade (broker 0.15% x2, levies 0.05% x2, SST 16% of
      commission, slippage) - ~0.85% round trip before a trade is
      worth anything.

  PICK                             The winner is NOT the best backtest.
      It is the rulebook with the best WORST session (leave-one-
      session-out scoring of a fixed rulebook: every stored day is a
      fold the rulebook must survive). Among ties at the top, prefer
      the more permissive rulebook - refusing less at equal robustness
      is worth more to the owner.

Outputs (committed by the cloud workflow):
  data/sweep/panels/<date>.jsonl   captured opportunities + paths
  data/sweep/results.json          full grid metrics
  data/sweep/REPORT.md             the human verdict
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psx_core import paths  # noqa: E402

PANEL_DIR = paths.DATA_DIR / "sweep" / "panels"
RESULTS_FILE = paths.DATA_DIR / "sweep" / "results.json"
REPORT_FILE = paths.DATA_DIR / "sweep" / "REPORT.md"

DECIDE_INTERVAL_S = 120.0  # capture cadence (live runs 180; finer here)
MIN_TRADES_FOR_WINNER = 8  # a "winner" on 3 trades is noise, not a rule
JUNK_SCORE_FLOOR = 0.40    # below this nothing is investable, don't record


# ---------------------------------------------------------------------------
# The owner's real cost stack (2026-09-14 specification)
# ---------------------------------------------------------------------------
BROKER_PCT = 0.15          # of traded value, each side (stocks >= Rs 20)
LEVIES_PCT = 0.05          # of traded value, each side
SST_OF_BROKER = 0.16       # Sindh sales tax on the commission, each side
SLIPPAGE_PCT = 0.20        # per side, conservative for KMIALL names


def round_trip_cost_pct() -> float:
    """True round-trip cost as a percentage of traded value."""
    per_side = BROKER_PCT + LEVIES_PCT + BROKER_PCT * SST_OF_BROKER
    return 2.0 * (per_side + SLIPPAGE_PCT)


COSTS_PCT = round(round_trip_cost_pct(), 3)


# ---------------------------------------------------------------------------
# Rulebook: every knob the grid may move, nothing else
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rulebook:
    # Stock gates
    min_master_score: float = 0.55
    require_above_vwap: bool = True
    min_evidence: int = 5
    min_day_value: float = 5_000_000.0
    max_entry_off_low_pct: float = 3.0     # 999 = chase cap off
    max_same_day_change_pct: float = 6.0   # 999 = cap off
    # Market gates
    hard_min_breadth_pct: float = 35.0     # 0 = floor off
    opening_hold_minutes: float = 15.0     # 0 = window off
    green_tape_only: bool = True           # market VW change >= 0
    # Exits (trail fixed at shipped values: activate +1.0%, trail 0.5%)
    profit_target_pct: float = 2.0
    max_loss_pct: float = 1.5

    def key(self) -> str:
        return "|".join(
            f"{v:g}" if isinstance(v, float) else str(v)
            for v in (
                self.min_master_score,
                self.require_above_vwap, self.min_evidence,
                self.min_day_value, self.max_entry_off_low_pct,
                self.max_same_day_change_pct, self.hard_min_breadth_pct,
                self.opening_hold_minutes, self.green_tape_only,
                self.profit_target_pct, self.max_loss_pct,
            )
        )


def grid() -> list[Rulebook]:
    """The honest search space: every gate the ledger ever blamed, plus
    the exit band the owner mandated (TP 2-3%), each at a few values."""
    books = []
    for (score, vwap, chase, day_cap, breadth, minutes,
         green, tp, sl) in itertools.product(
        (0.50, 0.55, 0.60),          # min_master_score
        (True,),                     # require_above_vwap
        (3.0, 5.0, 8.0, 999.0),      # chase cap
        (4.0, 6.0, 9.0, 999.0),      # same-day cap
        (0.0, 30.0, 35.0, 40.0),     # breadth floor (0 = off)
        (0.0, 30.0),                 # opening window (0 = off)
        (True, False),               # green tape only
        (2.0, 2.5, 3.0),             # profit target
        (1.0, 1.5, 2.0),             # stop loss
    ):
        books.append(Rulebook(
            min_master_score=score,
            require_above_vwap=vwap, max_entry_off_low_pct=chase,
            max_same_day_change_pct=day_cap,
            hard_min_breadth_pct=breadth,
            opening_hold_minutes=minutes,
            green_tape_only=green,
            profit_target_pct=tp, max_loss_pct=sl,
        ))
    return books


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def _leg_opens(date_str: str) -> list[int]:
    """Scheduled session leg opens (minutes-from-midnight PKT wall clock,
    the frame's timestamp convention) for the trading date."""
    try:
        from psx_core import sessions
        legs = sessions.legs_for(date_cls.fromisoformat(date_str))
        return sorted({l.start.hour * 60 + l.start.minute for l in legs})
    except Exception:  # noqa: BLE001 - no schedule info: morning only
        return [9 * 60 + 32]


def _minutes_since_open(ts: datetime, leg_opens: list[int]) -> float | None:
    """Engine semantics: minutes since the day's FIRST scheduled open,
    morning leg only. An afternoon leg's own opening minutes are not a
    fresh open (orderly re-opening flow); once past them, the noisy
    window does not apply. None = unknown clock (gate passes)."""
    if not leg_opens:
        return None
    m = ts.hour * 60 + ts.minute
    if m < leg_opens[0]:
        return None
    for open_m in leg_opens[1:]:
        if m < open_m:
            break
        if m < open_m + 30:
            return None  # inside a later leg's own open window
        return 999.0    # afternoon, well past its leg open
    return float(m - leg_opens[0])


def capture_date(date: str, out_path: Path | None = None) -> int:
    """Record every decide-step candidate + forward path for one session."""
    import build_intraday_dataset as intraday_builder
    import replay as replay_mod
    from psx_core import universe as universe_mod

    out_path = out_path or (PANEL_DIR / f"{date}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    symbols = universe_mod.load()
    all_rows: list[dict] = []
    for ts, rows in replay_mod.iter_day_rows(
        date,
        symbols,
        quote_to_row=intraday_builder.quote_to_row,
        empty_quote=intraday_builder._EMPTY_QUOTE,
    ):
        all_rows.extend(rows)
    if not all_rows:
        return 0
    base = pd.DataFrame(all_rows)
    del all_rows
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)
    base_sorted = base.sort_values(
        ["symbol", "timestamp"]
    ).reset_index(drop=True)
    ts_col = base_sorted["timestamp"]

    # Per-symbol close series for forward paths.
    series: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    priced = base[["symbol", "timestamp", "price"]].dropna()
    priced = priced[priced["price"] > 0]
    for symbol, group in priced.groupby("symbol", sort=False):
        pts = sorted(
            zip(
                pd.to_datetime(group["timestamp"]),
                group["price"].astype(float),
            )
        )
        series[symbol] = pts

    leg_opens = _leg_opens(date)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for decision_time in replay_mod._decide_grid(
            ts_col, DECIDE_INTERVAL_S
        ):
            mask = ts_col <= decision_time
            if not mask.any():
                continue
            df = base_sorted[mask.values].copy()
            if df.empty:
                continue
            try:
                df = replay_mod._transform_dataset(
                    df, intraday_builder, features_ns()
                )
            except Exception:  # noqa: BLE001 - a bad step loses one row
                continue
            latest = df[df["timestamp"] == df["timestamp"].max()]
            if latest.empty:
                continue

            rec = _best_candidate(latest, decision_time, leg_opens)
            if rec is None:
                continue
            rec["path"] = _forward_path(
                series.get(rec["symbol"], []), decision_time
            )
            rec["date"] = date
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            written += 1
    return written


def features_ns():
    """The features builder module (lazy: pandas import cost once)."""
    import build_kmiall_features as fmod
    return fmod


def _best_candidate(
    latest: pd.DataFrame, decision_time: datetime, leg_opens: list[int]
) -> dict | None:
    """The loosest honest pool: tradable, scored, liquid-ish - then the
    top row by score. Gate VALUES are recorded, not applied."""
    if "tradable" not in latest.columns:
        return None
    c = latest[latest["tradable"] == True].copy()  # noqa: E712
    score_col = (
        "feature_rank_score_adjusted"
        if "feature_rank_score_adjusted" in c.columns else None
    )
    if score_col is None:
        return None
    c = c[c[score_col].notna()]
    if "value" in c.columns:
        c = c[pd.to_numeric(c["value"], errors="coerce") >= 1_000_000]
    if c.empty:
        return None

    pick_col = "master_score" if "master_score" in c.columns else score_col
    c = c.sort_values(pick_col, ascending=False)
    best = c.iloc[0]
    pick = float(best[pick_col])
    if not math.isfinite(pick) or pick < JUNK_SCORE_FLOOR:
        return None

    def _f(series: pd.Series, col: str) -> float:
        if col not in series.index:
            return float("nan")
        v = pd.to_numeric(series[col], errors="coerce")
        return float(v) if pd.notna(v) else float("nan")

    # Evidence: exactly what the engine counts - non-NaN z_* components
    # on the row (fallback rank_*).
    z_cols = [col for col in best.index if str(col).startswith("z_")]
    if z_cols:
        evidence = int(sum(1 for col in z_cols if pd.notna(best[col])))
    else:
        r_cols = [col for col in best.index if str(col).startswith("rank_")]
        evidence = int(sum(1 for col in r_cols if pd.notna(best[col])))

    sector = str(best.get("sector", "")) if "sector" in best.index else ""
    sector_change = float("nan")
    if sector and "sector" in c.columns and "change_pct" in c.columns:
        grp = c[c["sector"] == sector]["change_pct"]
        sector_change = float(pd.to_numeric(grp, errors="coerce").mean())

    breadth = _f(best, "breadth_pct")
    off_low = _f(best, "distance_from_low_pct")
    change = _f(best, "change_pct")
    vwap_ratio = _f(best, "vwap_ratio")
    day_value = _f(best, "value")
    market_vw = _f(best, "market_vw_change_pct")

    return {
        "ts": decision_time.strftime("%H:%M"),
        "ts_min": decision_time.hour * 60 + decision_time.minute,
        "symbol": str(best["symbol"]),
        "price": round(float(best["price"]), 3),
        "score": round(pick, 4),
        "vwap_ratio": None if math.isnan(vwap_ratio) else round(vwap_ratio, 4),
        "evidence": evidence,
        "off_low": None if math.isnan(off_low) else round(off_low, 3),
        "change_pct": None if math.isnan(change) else round(change, 3),
        "day_value": None if math.isnan(day_value) else round(day_value, 0),
        "breadth": None if math.isnan(breadth) else round(breadth, 2),
        "market_vw": None if math.isnan(market_vw) else round(market_vw, 3),
        "minutes_open": _minutes_since_open(decision_time, leg_opens),
        "sector": sector,
        "sector_change": (
            None if math.isnan(sector_change) else round(sector_change, 3)
        ),
    }


def _forward_path(
    pts: list[tuple[pd.Timestamp, float]], entered_at: datetime,
    max_points: int = 420,
) -> list[list[float]]:
    """Forward price path after entry: [[minute_offset, price]…]."""
    t0 = pd.Timestamp(entered_at).timestamp()
    out = []
    for ts, price in pts:
        dt_min = (ts.timestamp() - t0) / 60.0
        # Forward ONLY: the entry tick itself (within a second) starts
        # the path; pre-entry ticks must never price an exit.
        if dt_min < -1.0 / 60.0:
            continue
        out.append([round(max(dt_min, 0.0), 2), round(float(price), 3)])
        if len(out) >= max_points:
            break
    return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def _passes_market_gates(row: dict, rb: Rulebook) -> bool:
    breadth = row.get("breadth")
    if breadth is not None and breadth < rb.hard_min_breadth_pct:
        return False
    minutes = row.get("minutes_open")
    if minutes is not None and minutes < rb.opening_hold_minutes:
        return False
    if rb.green_tape_only:
        vw = row.get("market_vw")
        if vw is None or vw < 0.0:
            return False
    return True


def _passes_stock_gates(row: dict, rb: Rulebook) -> bool:
    if row["score"] < rb.min_master_score:
        return False
    # v3.1.1: the Kalman gate is retired from the sweep rulebook.
    if rb.require_above_vwap:
        vr = row.get("vwap_ratio")
        # vwap_ratio = price/vwap - 1: ABOVE vwap is >= 0, not >= 1.
        if vr is None or vr < 0.0:
            return False
    if row["evidence"] < rb.min_evidence:
        return False
    dv = row.get("day_value")
    if dv is not None and dv < rb.min_day_value:
        return False
    off_low = row.get("off_low")
    if off_low is not None and off_low > rb.max_entry_off_low_pct:
        return False
    change = row.get("change_pct")
    if change is not None and change > rb.max_same_day_change_pct:
        return False
    return True


def _price_exit(
    path: list[list[float]], entry_price: float, rb: Rulebook
) -> tuple[float, float] | None:
    """Walk the stored path through TP/SL/trail. Returns
    (net_pnl_pct, exit_minute_offset) - net of the real fee stack.
    Un-triggered positions time-exit at the last stored price."""
    if not path:
        return None
    tp = entry_price * (1.0 + rb.profit_target_pct / 100.0)
    sl = entry_price * (1.0 - rb.max_loss_pct / 100.0)
    trail_act = entry_price * (1.0 + 1.0 / 100.0)
    best = entry_price
    trail_stop = None
    last_px = entry_price
    last_min = 0.0
    for off_min, px in path:
        if off_min < 0:
            continue  # pre-entry tick - history must never price an exit
        last_px = px
        last_min = off_min
        best = max(best, px)
        if px <= sl:
            return (-rb.max_loss_pct - COSTS_PCT, off_min)
        if px >= tp:
            return (rb.profit_target_pct - COSTS_PCT, off_min)
        if px >= trail_act:
            trail_stop = best * (1.0 - 0.5 / 100.0)
        if trail_stop is not None and px <= trail_stop:
            pnl = (px / entry_price - 1.0) * 100.0 - COSTS_PCT
            return (round(pnl, 4), off_min)
    pnl = (last_px / entry_price - 1.0) * 100.0 - COSTS_PCT
    return (round(pnl, 4), last_min)


@dataclass
class SimResult:
    n: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    max_consec_losses: int = 0
    session_pnls: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.session_pnls is None:
            self.session_pnls = []


def simulate(panels: list[list[dict]], rb: Rulebook) -> SimResult:
    """One rulebook over all captured sessions with an honest book:
    one position at a time (the slot frees at the position's exit
    minute), no re-entry while held, 3 entries/day."""
    res = SimResult()
    for session in panels:
        held_until = -1.0     # minute offset until which the slot is busy
        held_symbol = None
        entries_today = 0
        day = None
        consec = 0
        pnls: list[float] = []
        for row in sorted(session, key=lambda r: r["ts_min"]):
            if row["date"] != day:
                day = row["date"]
                entries_today = 0
                held_symbol = None
            if entries_today >= 3:
                continue
            if row["ts_min"] < held_until:
                continue  # position still open - slot busy
            if held_symbol == row["symbol"]:
                continue  # defensive; held_until normally covers it
            if not _passes_market_gates(row, rb):
                continue
            if not _passes_stock_gates(row, rb):
                continue
            priced = _price_exit(row["path"], row["price"], rb)
            if priced is None:
                continue
            pnl, exit_min = priced
            res.n += 1
            res.total_pnl += pnl
            pnls.append(pnl)
            if pnl > 0:
                res.wins += 1
                consec = 0
            else:
                consec += 1
                res.max_consec_losses = max(res.max_consec_losses, consec)
            entries_today += 1
            held_until = row["ts_min"] + exit_min
            held_symbol = row["symbol"]
        res.session_pnls.append(pnls)
    return res


def evaluate(
    panels: list[list[dict]], books: list[Rulebook] | None = None
) -> dict:
    """Grid every rulebook; rank by worst-session robustness."""
    books = books or grid()
    rows = []
    for rb in books:
        res = simulate(panels, rb)
        if res.n == 0:
            continue
        fold_avgs = [
            (sum(f) / len(f)) if f else 0.0 for f in res.session_pnls
        ]
        rows.append({
            "rulebook": rb.__dict__,
            "key": rb.key(),
            "n": res.n,
            "win_rate": round(res.wins / res.n, 4),
            "total_pnl_pct": round(res.total_pnl, 2),
            "avg_pnl_pct": round(res.total_pnl / res.n, 4),
            "max_consec_losses": res.max_consec_losses,
            "worst_session_avg": round(min(fold_avgs), 4),
            "mean_session_avg": round(
                sum(fold_avgs) / len(fold_avgs), 4
            ),
            "session_avgs": [round(f, 3) for f in fold_avgs],
        })

    eligible = [r for r in rows if r["n"] >= MIN_TRADES_FOR_WINNER]
    eligible.sort(
        key=lambda r: (
            r["worst_session_avg"], r["n"], r["total_pnl_pct"],
        ),
        reverse=True,
    )
    rows.sort(key=lambda r: r["total_pnl_pct"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "costs_pct_per_trade": COSTS_PCT,
        "sessions": len(panels),
        "configs_tested": len(rows),
        "min_trades_for_winner": MIN_TRADES_FOR_WINNER,
        "winner": eligible[0] if eligible else None,
        "ranking_robust": eligible[:25],
        "ranking_by_total": rows[:25],
    }


def load_panels() -> list[list[dict]]:
    panels = []
    if not PANEL_DIR.exists():
        return panels
    for f in sorted(PANEL_DIR.glob("*.jsonl")):
        session = []
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    session.append(json.loads(line))
        if session:
            panels.append(session)
    return panels


def write_report(results: dict, top_n: int = 12) -> str:
    winner = results.get("winner")
    top = results.get("ranking_robust", [])[:top_n]
    lines = [
        "# The Sentinel - rule sweep verdict",
        "",
        f"Generated {results['generated_at']}",
        f"Cost model: {results['costs_pct_per_trade']}% round trip/trade",
        f"Sessions: {results['sessions']}  |  "
        f"Rulebooks tested: {results['configs_tested']}",
        "",
        "Picked by worst-session robustness: the rulebook whose WORST "
        "single stored day was best, among those with at least "
        f"{results['min_trades_for_winner']} trades. Not the biggest "
        "backtest - the most survivable one.",
        "",
    ]
    if winner:
        rb = winner["rulebook"]
        lines += [
            "## The picked rulebook",
            "",
            f"- master score >= **{rb['min_master_score']}**, "
            f"VWAP required: **{rb['require_above_vwap']}**",
            f"- breadth floor **{rb['hard_min_breadth_pct']:g}%**, "
            f"opening window **{rb['opening_hold_minutes']:g} min**, "
            f"green tape only: **{rb['green_tape_only']}**",
            f"- chase cap **{rb['max_entry_off_low_pct']:g}%**, "
            f"same-day cap **{rb['max_same_day_change_pct']:g}%**",
            f"- exits: TP **{rb['profit_target_pct']}%** / SL "
            f"**{rb['max_loss_pct']}%**, trail +1.0% -> 0.5%",
            f"- record: **{winner['n']} trades, "
            f"{winner['win_rate']*100:.0f}% wins, "
            f"{winner['avg_pnl_pct']:+.2f}% avg/trade NET of costs**, "
            f"worst session {winner['worst_session_avg']:+.2f}%",
            "",
        ]
    else:
        lines += [
            "## No rulebook qualified",
            "",
            f"Nothing reached {results['min_trades_for_winner']} trades "
            "with a non-negative worst session. The honest answer today "
            "is: the stored tape does not yet support a profitable "
            "intraday long rulebook at these costs. More sessions of "
            "data are needed - not looser standards.",
            "",
        ]
    lines += [
        "## Top rulebooks by worst-session robustness",
        "",
        "| # | score>= | breadth>= | window>= | chase<= | "
        "day<= | green | TP% | SL% | n | win% | avg% | worst-day% |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top, 1):
        rb = r["rulebook"]
        lines.append(
            f"| {i} | {rb['min_master_score']} "
            f"| {rb['hard_min_breadth_pct']:g} "
            f"| {rb['opening_hold_minutes']:g} "
            f"| {rb['max_entry_off_low_pct']:g} "
            f"| {rb['max_same_day_change_pct']:g} "
            f"| {rb['green_tape_only']} | {rb['profit_target_pct']:g} "
            f"| {rb['max_loss_pct']:g} | {r['n']} "
            f"| {r['win_rate']*100:.0f}% | {r['avg_pnl_pct']:+.2f} "
            f"| {r['worst_session_avg']:+.2f} |"
        )
    lines += [
        "",
        "_Net figures include the full cost stack (broker, levies, SST, "
        "slippage). Panels: every decide-step best candidate across all "
        "stored sessions, with forward paths. The bot applies the "
        "picked rulebook only after this table says it is worth "
        "applying._",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--capture" in argv:
        # INCREMENTAL (2026-09-20): scheduled sweeps used to re-capture
        # every session and died at the 6-hour job ceiling once the
        # stored tape grew past 7 sessions (2026-09-19 timeout, 5h50m
        # in step 1). Panels are rulebook-agnostic - gate VALUES are
        # recorded, not applied - so an existing panel is reused as-is;
        # only new sessions are walked. A capture-pool change (the
        # structural filters in _best_candidate) requires --force.
        import replay as replay_mod
        force = "--force" in argv
        dates = [a.split("=", 1)[1] for a in argv if a.startswith("--date=")]
        for d in (dates or replay_mod.stored_dates()):
            out = PANEL_DIR / f"{d}.jsonl"
            if not force and out.exists() and out.stat().st_size > 0:
                print(f"captured {d}: panel exists - skipped", flush=True)
                continue
            n = capture_date(d)
            print(f"captured {d}: {n} opportunities", flush=True)
        return 0
    if "--evaluate" in argv:
        panels = load_panels()
        if not panels:
            print("No panels captured yet - run --capture first.")
            return 1
        results = evaluate(panels)
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_FILE.write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
        REPORT_FILE.write_text(write_report(results), encoding="utf-8")
        print(
            f"evaluated {results['configs_tested']} rulebooks over "
            f"{results['sessions']} sessions"
        )
        w = results.get("winner")
        if w:
            print(
                f"winner: n={w['n']} win={w['win_rate']*100:.0f}% "
                f"avg={w['avg_pnl_pct']:+.2f}% "
                f"worst-session={w['worst_session_avg']:+.2f}% "
                f"rulebook={w['rulebook']}"
            )
        else:
            print("no rulebook qualified - see REPORT.md")
        return 0
    print(
        "usage: sweep.py --capture [--date=YYYY-MM-DD] [--force]"
        " | --evaluate"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
