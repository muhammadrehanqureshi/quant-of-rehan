"""Grind 9 - the combo test: refinements A (prev-day value floor) and
C (volume-ratio ceiling) each survived both halves in grind 8. Combos
and the per-symbol memory gate, on the full corpus, same discipline.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from backtest_grind8_fullcorpus import (  # noqa: E402
    load_daily, sessions_index, candidates, next_day_outcome, stats,
)


def simulate2(daily, dates, pick, start, end):
    trades = []
    for dt in dates:
        if not (start <= dt <= end):
            continue
        cands = []
        for sym, feat in candidates(daily, dates, dt):
            if feat["value_m"] >= 500:      # distribution trap (v2.3)
                continue
            score = pick(sym, feat)
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
        net = res - (0.848 if res > 0 else 0.848)
        trades.append({"date": dt, "sym": sym, "net": net})
    return trades


def main():
    daily = load_daily()
    dates = sessions_index(daily)
    split = dates[int(len(dates) * 0.6)]
    d0, d1 = dates[0], dates[-1]
    d_end = dates[int(len(dates) * 0.6) - 1]

    # trailing lock memory per symbol (no look-ahead: uses only events
    # before the current date)
    lock_events = {}  # sym -> list[(date, next_chg)]
    for sym, rs in daily.items():
        ev = []
        for i in range(1, len(rs) - 1):
            p, r = rs[i - 1], rs[i]
            if not p.get("close") or p["close"] <= 0:
                continue
            chg = (r["close"] / p["close"] - 1) * 100
            if chg >= 9.9:
                nxt = rs[i + 1]
                ev.append((r["date"], (nxt["close"] / r["close"] - 1) * 100))
        lock_events[sym] = ev

    def mem_state(sym, dt):
        past = [1 if c >= 2.0 else 0 for d, c in lock_events.get(sym, []) if d < dt]
        if len(past) < 3:
            return None  # unknown
        return sum(past) / len(past)

    def base(sym, feat):
        if feat["chg"] < 9.9:
            return None
        return feat["chg"]

    def combo(sym, feat):
        if feat["chg"] < 9.9:
            return None
        if feat["vol_ratio"] > 5.0:
            return None
        prev_val_m = feat["prev_vol"] * feat["close"] / 1e6
        if prev_val_m < 0.5:
            return None
        return feat["chg"]

    def combo_mem(sym, feat, dt_holder={}):
        s = combo(sym, feat)
        if s is None:
            return None
        m = mem_state(sym, dt_holder.get("d", ""))
        if m is not None and m < 0.5:
            return None  # chronic fake: own record below 50%
        return s

    tests = [
        ("baseline v2.3", base),
        ("combo A+C", combo),
    ]

    print("grind 9 - combos on the full 175-session corpus\n")
    for name, fn in tests:
        dd = simulate2(daily, dates, fn, d0, d_end)
        vv = simulate2(daily, dates, fn, split, d1)
        print(f"{name}:")
        print(f"  disc[{stats(dd)}]  val[{stats(vv)}]")

    # memory-gated combo needs the date - do it in a dedicated loop
    def run_mem(start, end):
        trades = []
        for dt in dates:
            if not (start <= dt <= end):
                continue
            cands = []
            for sym, feat in candidates(daily, dates, dt):
                if feat["value_m"] >= 500:
                    continue
                if feat["chg"] < 9.9 or feat["vol_ratio"] > 5.0:
                    continue
                prev_val_m = feat["prev_vol"] * feat["close"] / 1e6
                if prev_val_m < 0.5:
                    continue
                m = mem_state(sym, dt)
                if m is not None and m < 0.5:
                    continue
                cands.append((feat["chg"], sym, feat))
            if not cands:
                continue
            cands.sort(reverse=True)
            _, sym, _ = cands[0]
            rs = daily[sym]
            idx = next(i for i, r in enumerate(rs) if r["date"] == dt)
            res = next_day_outcome(rs, idx, None)
            if res is None:
                continue
            trades.append({"date": dt, "sym": sym, "net": res - 0.848})
        return trades

    dd = run_mem(d0, d_end)
    vv = run_mem(split, d1)
    print("combo A+C + per-symbol memory gate (record <50% refused):")
    print(f"  disc[{stats(dd)}]  val[{stats(vv)}]")


if __name__ == "__main__":
    main()
