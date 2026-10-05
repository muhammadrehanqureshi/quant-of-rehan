"""Grind 8 - the EOD lock policy re-validated on the FULL 175-session
corpus (the v2.3 policy was tuned on 30 sessions), plus two new entry-time
refinements mined with the same discovery/validation discipline.

Law under test (owner's universal law): entry at pick-day close,
TP +2.0% / SL -1.0% on the next session, force-close if neither hits.
Cost stack: 0.848% round trip (commission + SST + levies + CGT on wins).

Honesty rules:
  * every feature is knowable at 15:29 on pick day (no look-ahead);
  * discovery half = first 60% of sessions, validation half = last 40%;
  * a refinement ships only if BOTH halves beat the baseline.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"

TP, SL = 2.0, -1.0
COST = 0.848  # round-trip %


def load_daily():
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    daily = {}
    for sym, rows in data.items():
        rs = sorted(rows, key=lambda r: r["date"])
        daily[sym] = rs
    return daily


def sessions_index(daily):
    dates = set()
    for rs in daily.values():
        for r in rs:
            dates.add(r["date"])
    return sorted(dates)


def prev_row(rs, i):
    return rs[i - 1] if i > 0 else None


def next_day_outcome(rs, i, open_map):
    """Close-to-close law outcome on the NEXT session.

    Honest limitation, same as the shipped policy backtests: the DPS
    corpus has no intraday high/low, so TP/SL touches cannot be walked.
    The outcome is the next session's close bracketed to the law -
    identical to backtest_eod_policy.py that produced the shipped
    numbers. (A touch-based sim here would fabricate data.)
    """
    if i + 1 >= len(rs):
        return None
    nd = rs[i + 1]
    entry = rs[i]["close"]
    if not nd.get("close") or nd["close"] <= 0 or entry <= 0:
        return None
    ret = (nd["close"] / entry - 1) * 100
    if ret >= TP:
        return TP
    if ret <= SL:
        return SL
    return ret


def candidates(daily, dates, i_date):
    """Pick-day candidates: the >=8% close bracket with the vetoes."""
    out = []
    for sym, rs in daily.items():
        for i, r in enumerate(rs):
            if r["date"] != i_date:
                continue
            p = prev_row(rs, i)
            if not p or not p.get("close") or p["close"] <= 0:
                continue
            chg = (r["close"] / p["close"] - 1) * 100
            if chg < 8.0:
                continue
            body = (r["close"] - r.get("open", r["close"])) / r["close"] * 100
            vol_ratio = (r.get("volume") or 0) / max(p.get("volume") or 1, 1)
            yield sym, {
                "chg": chg,
                "body": body,
                "vol_ratio": vol_ratio,
                "close": r["close"],
                "vol": r.get("volume") or 0,
                "prev_vol": p.get("volume") or 0,
                "value_m": (r.get("volume") or 0) * r["close"] / 1e6,
            }
            break  # one row per symbol per day


def simulate(daily, dates, ranks, start, end):
    """One pick per day: top-ranked candidate; returns net list."""
    trades = []
    for dt in dates:
        if not (start <= dt <= end):
            continue
        cands = []
        for sym, feat in candidates(daily, dates, dt):
            # policy vetoes (v2.3): distribution trap, dead volume
            if feat["value_m"] >= 500:
                continue  # distribution trap
            if feat["vol_ratio"] < 0.5:
                continue  # no participation
            score = ranks(sym, feat)
            if score is None:
                continue
            cands.append((score, sym, feat))
        if not cands:
            continue
        cands.sort(reverse=True)
        _, sym, feat = cands[0]
        rs = daily[sym]
        idx = next(i for i, r in enumerate(rs) if r["date"] == dt)
        res = next_day_outcome(rs, idx, None)
        if res is None:
            continue
        net = res - COST if res > 0 else res - COST
        trades.append({"date": dt, "sym": sym, "gross": res, "net": net})
    return trades


def stats(trades):
    if not trades:
        return "n=0"
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    return (f"n={len(trades)} win={100*len(wins)/len(nets):.1f}% "
            f"net={sum(nets)/len(nets):+.2f}/t total={sum(nets):+.1f}")


def main():
    daily = load_daily()
    dates = sessions_index(daily)
    d0, d1 = dates[0], dates[-1]
    split = dates[int(len(dates) * 0.6)]
    print(f"corpus: {len(dates)} sessions {d0}..{d1} "
          f"({len(daily)} symbols), split at {split}\n")

    def base_rank(sym, feat):
        # v2.3: locked closes only, rank by change (lock_days proxy)
        if feat["chg"] < 9.9:
            return None
        return feat["chg"]

    full = simulate(daily, dates, base_rank, d0, d1)
    disc = simulate(daily, dates, base_rank, d0, dates[int(len(dates)*0.6)-1])
    val = simulate(daily, dates, base_rank, split, d1)
    print("BASELINE v2.3 policy (locked>=9.9, rank by chg):")
    print("  discovery:", stats(disc))
    print("  validation:", stats(val))
    print("  full:", stats(full))
    print()

    # --- Refinement A: prior-day volume collapse (a real trap: the lock
    # fired on near-zero volume with no follow-through behind it)
    print("REFINEMENT A - prior-day traded value floor:")
    for floor in [0.5, 1.0, 2.0]:
        def rank_a(sym, feat, fl=floor):
            if feat["chg"] < 9.9:
                return None
            prev_val_m = feat["prev_vol"] * feat["close"] / 1e6
            if prev_val_m < fl:
                return None
            return feat["chg"]
        a_d = simulate(daily, dates, rank_a, d0, dates[int(len(dates)*0.6)-1])
        a_v = simulate(daily, dates, rank_a, split, d1)
        print(f"  prev-day value >= {floor}M: disc[{stats(a_d)}] val[{stats(a_v)}]")
    print()

    # --- Refinement B: body quality - a lock on a weak body (close far
    # below high) is exhaustion, not continuation
    print("REFINEMENT B - close position in day range (needs high): ")
    # corpus lacks high/low; skip honestly
    print("  SKIPPED - corpus has no day high/low; refusing to fake it")
    print()

    # --- Refinement C: volume ratio ceiling - 20x+ volume on a lock is
    # often one-way distribution into the close
    print("REFINEMENT C - volume-ratio ceiling:")
    for ceil in [5.0, 10.0, 20.0]:
        def rank_c(sym, feat, c=ceil):
            if feat["chg"] < 9.9:
                return None
            if feat["vol_ratio"] > c:
                return None
            return feat["chg"]
        c_d = simulate(daily, dates, rank_c, d0, dates[int(len(dates)*0.6)-1])
        c_v = simulate(daily, dates, rank_c, split, d1)
        print(f"  vol_ratio <= {ceil}: disc[{stats(c_d)}] val[{stats(c_v)}]")


if __name__ == "__main__":
    main()
