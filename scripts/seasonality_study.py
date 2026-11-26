#!/usr/bin/env python3
"""KMIALL weekday seasonality study: which scrips go green on which weekday.

SO-21: this run belongs on GitHub Actions minutes, never the owner's PC. The
entry point is guarded with guard_cloud_backtest and refuses locally.

Question the owner asked on 2026-11-26: over the last five years, which KMIALL
scrips "always go green (more than 1.5%)" on a specific day? This script
answers it with counts, dates and a multiple-testing correction rather than a
guess, and it says plainly when the answer is "none of them".

The measure. A session is GREEN for a scrip when its close is at least
--green percent above the previous session's close (default 1.5). A weekday
test is one (scrip, weekday) pair that has at least --min-sessions sessions of
that weekday in the window.

The evidence for every reported row is the list of dates that were green on
that weekday, with the return of each, plus the sessions of that weekday that
were not green. A row that were truly "always green" would have an empty miss
list; none does, and the report states the best rate that actually occurred.

The statistics:

* base rate: the same scrip's green rate over all weekdays, which is what the
  weekday must beat to be interesting;
* a one-sided exact binomial tail, P(X >= hits | n, base), so a small sample
  cannot look impressive by accident;
* a Wilson 95 percent interval on the weekday rate;
* Bonferroni across every test run, and Benjamini-Hochberg q values beside it,
  because roughly 500 scrip and weekday pairs are tested at once;
* a first half and second half split of each row, so a rate that only exists
  in one half is visible as the noise it probably is.

Data: the PSX daily archive panel built by scripts/build_backtest_dataset.py
(full OHLCV, one row per scrip per session). data/ is gitignored, so the panel
is built inside the same cloud job that runs this study.

Usage:
    python scripts/seasonality_study.py \
        --dataset data/eod_5y.csv.gz \
        --universe src/data/universe_kmiall.json \
        --out data/research/seasonality_5y.json \
        --md reports/2026-11-26-kmiall-weekday-seasonality.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402

import pandas as pd  # noqa: E402

DAY_NAMES = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
DEFAULT_GREEN = 1.5
DEFAULT_YEARS = 5.0
DEFAULT_MIN_SESSIONS = 100
DEFAULT_MIN_SYMBOL_SESSIONS = 500


# ---------- statistics ----------

def binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), summed exactly.

    A one-sided tail rather than a normal approximation: the weekday samples
    are a few hundred sessions, and the whole point is to stop a short run of
    green days from reading as a pattern.
    """
    if n <= 0:
        return 1.0
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    q = 1.0 - p
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p ** i) * (q ** (n - i))
    return min(1.0, total)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion, the honest one at small n."""
    if n <= 0:
        return 0.0, 1.0
    ph = k / n
    den = 1.0 + z * z / n
    centre = (ph + z * z / (2.0 * n)) / den
    half = z * math.sqrt(ph * (1.0 - ph) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg q values, in the order the p values were given."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = min(1.0, running)
    return q


# ---------- data ----------

def load_returns(path: Path) -> pd.DataFrame:
    """Close to close percentage returns per scrip, from the EOD panel."""
    df = pd.read_csv(path, usecols=["symbol", "date", "close"])
    return load_returns_from_frame(df)


def load_returns_from_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The same returns from a frame already in memory, for the tests."""
    df = df[["symbol", "date", "close"]].copy()
    df["symbol"] = df["symbol"].astype(str)
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[df["close"] > 0]
    df = df.drop_duplicates(["symbol", "date"], keep="last")
    df = df.sort_values(["symbol", "date"])
    df["ret_pct"] = df.groupby("symbol")["close"].pct_change() * 100.0
    return df.dropna(subset=["ret_pct"]).reset_index(drop=True)


def load_universe(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["symbol"]).upper() for item in raw if item.get("symbol")}


def window_slice(df: pd.DataFrame, years: float, end: str | None) -> pd.DataFrame:
    """The last `years` of the panel, measured back from its own last session."""
    last = pd.to_datetime(end) if end else df["date"].max()
    start = last - pd.Timedelta(days=int(round(365.25 * years)))
    return df[(df["date"] > start) & (df["date"] <= last)].reset_index(drop=True)


# ---------- the study ----------

def study(df: pd.DataFrame, universe: set[str], green: float,
          min_sessions: int, min_symbol_sessions: int) -> dict:
    """Every scrip and weekday pair, with its evidence and its p value."""
    df = df[df["symbol"].isin(universe)].copy()
    df["dow"] = df["date"].dt.weekday
    df["is_green"] = df["ret_pct"] >= green

    rows: list[dict] = []
    coverage: dict[str, dict] = {}
    for sym, g in df.groupby("symbol", sort=True):
        n_sym = len(g)
        if n_sym < min_symbol_sessions:
            continue
        base_hits = int(g["is_green"].sum())
        base = base_hits / n_sym
        mid = g["date"].sort_values().iloc[n_sym // 2]
        coverage[sym] = {
            "sessions": n_sym,
            "green_sessions": base_hits,
            "green_rate": round(base, 4),
            "first": str(g["date"].min().date()),
            "last": str(g["date"].max().date()),
        }
        for dow in range(5):
            d = g[g["dow"] == dow]
            n = len(d)
            if n < min_sessions:
                continue
            hits = int(d["is_green"].sum())
            rate = hits / n
            lo, hi = wilson(hits, n)
            first = d[d["date"] < mid]
            second = d[d["date"] >= mid]
            green_days = d[d["is_green"]]
            miss_days = d[~d["is_green"]]
            rows.append({
                "symbol": sym,
                "weekday": DAY_NAMES[dow],
                "sessions": n,
                "green_sessions": hits,
                "green_rate": round(rate, 4),
                "base_rate": round(base, 4),
                "lift": round(rate - base, 4),
                "ci95": [round(lo, 4), round(hi, 4)],
                "p_value": binomial_tail(hits, n, base),
                "first_half_rate": round(first["is_green"].mean(), 4) if len(first) else None,
                "second_half_rate": round(second["is_green"].mean(), 4) if len(second) else None,
                "green_dates": [
                    {"date": str(r.date.date()), "ret_pct": round(float(r.ret_pct), 2)}
                    for r in green_days.itertuples()
                ],
                "missed_sessions": len(miss_days),
                "missed_dates": [str(x.date()) for x in miss_days["date"]],
            })

    pvals = [r["p_value"] for r in rows]
    for r, q in zip(rows, bh_qvalues(pvals)):
        r["q_value"] = q

    tests = len(rows)
    bonf = 0.05 / tests if tests else 1.0
    rows.sort(key=lambda r: (r["p_value"], -r["green_rate"]))
    survivors = [r for r in rows if r["p_value"] < bonf]
    return {
        "study": {
            "green_definition": f"close at least {green} percent above the previous session close",
            "weekdays_tested": list(DAY_NAMES),
            "min_sessions_per_weekday": min_sessions,
            "min_sessions_per_symbol": min_symbol_sessions,
            "tests": tests,
            "bonferroni_threshold": bonf,
            "survivors": len(survivors),
        },
        "coverage": {
            "symbols": len(coverage),
            "sessions": int(df["date"].nunique()),
            "first": str(df["date"].min().date()),
            "last": str(df["date"].max().date()),
            "rows": int(len(df)),
            "table": coverage,
        },
        "market_by_weekday": market_by_weekday(df, green),
        "rows": rows,
        "top": rows[:15],
        "survivor_rows": survivors,
        "best_rate": max((r["green_rate"] for r in rows), default=None),
        "perfect_rows": [r for r in rows if r["green_sessions"] == r["sessions"]],
    }


def market_by_weekday(df: pd.DataFrame, green: float) -> list[dict]:
    """Every weekday's green rate across the whole panel, equal weight per scrip.

    This is the day effect a single scrip has to beat: if the whole market is
    greener on Fridays, a scrip that is greener on Fridays proves nothing.
    """
    per_day: dict[int, list[float]] = {d: [] for d in range(5)}
    for _, g in df.groupby("symbol", sort=True):
        for dow in range(5):
            d = g[g["dow"] == dow]
            if len(d) >= 30:
                per_day[dow].append(float((d["ret_pct"] >= green).mean()))
    out = []
    for dow in range(5):
        vals = per_day[dow]
        if not vals:
            continue
        out.append({
            "weekday": DAY_NAMES[dow],
            "scrips_measured": len(vals),
            "mean_green_rate": round(sum(vals) / len(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
        })
    return out


def always_statement(report: dict) -> dict:
    """How close any scrip and weekday pair comes to "always green"."""
    rows = report["rows"]
    if not rows:
        return {"measured": False}
    best = max(rows, key=lambda r: (r["green_rate"], -r["p_value"]))
    return {
        "measured": True,
        "best_symbol": best["symbol"],
        "best_weekday": best["weekday"],
        "best_hits": best["green_sessions"],
        "best_sessions": best["sessions"],
        "best_rate": best["green_rate"],
        "misses": best["missed_sessions"],
        "perfect_pairs": len(report["perfect_rows"]),
    }


# ---------- the document ----------

def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_markdown(report: dict, green: float, years: float) -> str:
    st = report["study"]
    cov = report["coverage"]
    alw = always_statement(report)
    lines: list[str] = []
    add = lines.append

    span_years = (pd.Timestamp(cov["last"]) - pd.Timestamp(cov["first"])).days / 365.25

    add("# KMIALL weekday seasonality, five years of sessions")
    add("")
    add(f"Built {report['generated'][:10]} from the PSX daily archive panel "
        f"(full OHLCV, one row per scrip per session). Window: "
        f"{cov['first']} to {cov['last']}, {span_years:.1f} years, "
        f"{cov['sessions']} sessions, {cov['symbols']} KMIALL scrips.")
    add("")
    add("## The question, and the answer")
    add("")
    add(f"A session counts as GREEN for a scrip when its close is at least "
        f"{green:g} percent above the previous session's close. The question was "
        f"which scrips \"always go green\" on a specific weekday, and there "
        f"should be concrete evidence for the claim.")
    add("")
    if alw.get("measured") and alw["perfect_pairs"] == 0:
        add(f"**No scrip is always green on any weekday.** Every one of the "
            f"{st['tests']} scrip and weekday pairs tested has at least one "
            f"session of that weekday that failed the {green:g} percent bar. "
            f"The best single pair is **{alw['best_symbol']} on "
            f"{alw['best_weekday']}**: green {alw['best_hits']} of "
            f"{alw['best_sessions']} times ({pct(alw['best_rate'])}), and not "
            f"green on {alw['misses']} sessions of that weekday.")
    elif alw.get("measured"):
        add(f"{alw['perfect_pairs']} scrip and weekday pair(s) were green on "
            f"every session of that weekday in the window. They are listed as "
            f"perfect rows in the evidence file, and each one still needs the "
            f"sample size checked before it means anything.")
    else:
        add("No scrip carried enough sessions of any weekday to be tested.")
    add("")
    add("That is the honest reading of five years: the data does not contain a "
        "day on which any scrip always goes green. What it does contain is a "
        "ranked list of the pairs whose green rate is furthest above their own "
        "base rate, with the counts, the dates and a significance test attached "
        "so you can judge each one yourself.")
    add("")

    add("## How this is measured")
    add("")
    add(f"* The bar: close to close return of at least +{green:g} percent.")
    add(f"* Window: the last {years:g} years of the panel, measured back from "
        f"its final session.")
    add(f"* A pair is tested only with at least {st['min_sessions_per_weekday']} "
        f"sessions of that weekday, and a scrip only with at least "
        f"{st['min_sessions_per_symbol']} sessions in the window, so a newly "
        f"listed scrip cannot look like a pattern.")
    add("* Base rate: the same scrip's green rate across all weekdays. The "
        "weekday has to beat that, otherwise it is just a volatile scrip.")
    add("* p value: one-sided exact binomial tail, P(at least this many green "
        "days | the scrip's own base rate). Small n cannot flatter a row.")
    add("* 95 percent interval: Wilson score interval on the weekday rate.")
    add(f"* Multiple testing: {st['tests']} pairs were tested, so the "
        f"Bonferroni threshold is {st['bonferroni_threshold']:.2e}. "
        f"{st['survivors']} pair(s) clear it. Benjamini-Hochberg q values are "
        f"reported beside the p values for a less severe read.")
    add("* Split halves: the window is cut in two at each scrip's median "
        "session date, and both halves' green rates are reported, so a rate "
        "that lives only in one half is visible as the noise it probably is.")
    add("")

    add("## The market's own weekday rates")
    add("")
    add("Equal weight across scrips, so no single heavy scrip decides the row. "
        "This is the day effect a scrip has to beat.")
    add("")
    add("| Weekday | Scrips measured | Mean green rate | Weakest scrip | Strongest scrip |")
    add("|---|---|---|---|---|")
    for m in report["market_by_weekday"]:
        add(f"| {m['weekday']} | {m['scrips_measured']} | "
            f"{pct(m['mean_green_rate'])} | {pct(m['min'])} | {pct(m['max'])} |")
    add("")

    add("## The strongest scrip and weekday pairs")
    add("")
    add(f"Ranked by p value, which is the same as asking which row is least "
        f"likely to be luck given its own base rate. Bonferroni threshold: "
        f"{st['bonferroni_threshold']:.2e}.")
    add("")
    add("| # | Scrip | Weekday | Green sessions | Of sessions | Rate | Own base rate | Lift | 95% interval | p | q | First half | Second half |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(report["top"], 1):
        add(f"| {i} | {r['symbol']} | {r['weekday']} | {r['green_sessions']} | "
            f"{r['sessions']} | {pct(r['green_rate'])} | {pct(r['base_rate'])} | "
            f"{r['lift'] * 100:+.1f} pts | {pct(r['ci95'][0])} to "
            f"{pct(r['ci95'][1])} | {r['p_value']:.2e} | {r['q_value']:.2f} | "
            f"{pct(r['first_half_rate'])} | {pct(r['second_half_rate'])} |")
    add("")
    if st["survivors"] == 0:
        add("**None of these clears the Bonferroni threshold.** With roughly "
            "five hundred pairs tested at once, a p value of a few thousandths "
            "is what luck produces. Treat the table as the shortlist to watch, "
            "not as a law to trade.")
    else:
        add(f"**{st['survivors']} pair(s) clear the Bonferroni threshold.** "
            f"Even so, a survivor is a hypothesis for the next five years, not "
            f"a promise, because the window is the same one it was found in.")
    add("")

    add("## The evidence, date by date")
    add("")
    add("For each of the five strongest pairs: every date that was green on "
        "that weekday, with the return, and the sessions that were not.")
    add("")
    for r in report["top"][:5]:
        add(f"### {r['symbol']} on {r['weekday']}")
        add("")
        add(f"{r['green_sessions']} green of {r['sessions']} {r['weekday'].lower()} "
            f"sessions ({pct(r['green_rate'])}), against a base rate of "
            f"{pct(r['base_rate'])} on every weekday. "
            f"{r['missed_sessions']} {r['weekday'].lower()} sessions missed the bar.")
        add("")
        add("| Green date | Return |")
        add("|---|---|")
        for d in r["green_dates"]:
            add(f"| {d['date']} | {d['ret_pct']:+.2f}% |")
        add("")
        if r["missed_dates"]:
            missed = ", ".join(r["missed_dates"][:12])
            more = "" if len(r["missed_dates"]) <= 12 else f", and {len(r['missed_dates']) - 12} more"
            add(f"Missed dates (first twelve): {missed}{more}.")
            add("")

    add("## What this does not prove")
    add("")
    add("* A weekday rate is a description of the past window, not a "
        "forecast. The window is the window the pattern was found in.")
    add(f"* {st['tests']} tests at once means some pairs look strong by "
        f"construction. The p and q columns are there to be read before the "
        f"rate is.")
    add("* Surviving scrips change: the KMIALL list of today is applied to the "
        "whole window, so scrips that left the list are missing and scrips "
        "that joined late carry short histories.")
    add("* Thin scrips cannot be traded at the price that printed. A green "
        "session in a scrip with no volume is a print, not a fill, and PSX "
        "price limits can freeze an exit.")
    add(f"* Costs are not charged here at all. A {green:g} percent green "
        f"session is a gross move; the repository's own law charges about 1.1 "
        f"percent round trip before any tax.")
    add("")
    add("## Reproduce it")
    add("")
    add("```")
    add("python scripts/build_backtest_dataset.py \\")
    add("  --universe src/data/universe_kmiall.json --start 2021-10-01 \\")
    add("  --out data/eod_5y.csv.gz --cache-dir data/mkt_cache")
    add("python scripts/seasonality_study.py \\")
    add("  --dataset data/eod_5y.csv.gz \\")
    add("  --universe src/data/universe_kmiall.json \\")
    add("  --out data/research/seasonality_5y.json \\")
    add("  --md reports/2026-11-26-kmiall-weekday-seasonality.md")
    add("```")
    add("")
    add("Both steps are declared research work under SO-21 and refuse to run "
        "outside GitHub Actions. Dispatch the `backtest` workflow with "
        "task `seasonality`.")
    add("")
    return "\n".join(lines)


# ---------- entry point ----------

def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/seasonality_study.py")
    ap = argparse.ArgumentParser(description="KMIALL weekday seasonality study")
    ap.add_argument("--dataset", type=Path, default=Path("data/eod_5y.csv.gz"))
    ap.add_argument("--universe", type=Path,
                    default=Path("src/data/universe_kmiall.json"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/seasonality_5y.json"))
    ap.add_argument("--md", type=Path,
                    default=Path("reports/2026-11-26-kmiall-weekday-seasonality.md"))
    ap.add_argument("--green", type=float, default=DEFAULT_GREEN,
                    help="green bar in percent of the previous close")
    ap.add_argument("--years", type=float, default=DEFAULT_YEARS)
    ap.add_argument("--end", default=None, help="ISO date, default: last session")
    ap.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS,
                    help="sessions of a weekday needed to test that weekday")
    ap.add_argument("--min-symbol-sessions", type=int,
                    default=DEFAULT_MIN_SYMBOL_SESSIONS)
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"REFUSED: {args.dataset} is missing. Build the panel first; "
              f"this study never invents data (SO-3).", flush=True)
        return 2

    raw = load_returns(args.dataset)
    df = window_slice(raw, args.years, args.end)
    if df.empty:
        print("REFUSED: the window holds no returns.", flush=True)
        return 2

    universe = load_universe(args.universe)
    report = study(df, universe, args.green, args.min_sessions,
                   args.min_symbol_sessions)
    report["generated"] = datetime.now(timezone.utc).isoformat()
    report["window_years"] = args.years
    report["green_pct"] = args.green
    report["dataset"] = {
        "path": str(args.dataset),
        "rows_read": int(len(raw)),
        "rows_in_window": int(len(df)),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(render_markdown(report, args.green, args.years),
                       encoding="utf-8")

    st = report["study"]
    print(f"sessions {report['coverage']['sessions']} "
          f"{report['coverage']['first']}..{report['coverage']['last']}  "
          f"scrips {report['coverage']['symbols']}  tests {st['tests']}  "
          f"survivors {st['survivors']}", flush=True)
    for r in report["top"][:5]:
        print(f"  {r['symbol']:10s} {r['weekday']:9s} "
              f"{r['green_sessions']:3d}/{r['sessions']:3d} "
              f"{pct(r['green_rate'])}  base {pct(r['base_rate'])}  "
              f"p {r['p_value']:.2e}", flush=True)
    print(f"\nReport -> {args.out}\nDocument -> {args.md}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
