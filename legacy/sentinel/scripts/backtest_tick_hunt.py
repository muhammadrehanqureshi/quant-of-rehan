"""The tick hunt: can an EARLY trigger beat the old chase entries?

The owner's core complaint: entries come after the stock already ran
3-4%. The daily bars proved no open-to-close shape survives costs -
but intraday structure at snapshot resolution was never mined.

Tape: data/snapshots/*.jsonl.gz (13 sessions, ~297 quotes/snapshot,
5-12 min cadence, full bid/ask/vol + cumulative day high/low).

Trigger families (all measurable at snapshot time, no look-ahead):
  EARLY   - extension over prior close crosses into [+1.5, +2.5] from
            BELOW, on a day whose prior max extension stayed < +3
            (a fresh break, not a chase; needs prior-close history)
  PULLBK  - extension in [+2, +6] but down >= 0.8% from the day's
            running high (a dip within a real move)
  RECLM   - price reclaims the session VWAP after being below it
  CHASE   - extension >= +4 (the old behavior, for the A/B)

Simulated exits under the law (TP +2% / SL -1% from the trigger price,
cloud-observable fills):
  price >= entry*1.02                    -> WIN  (poll prints are real)
  price <= entry*0.99                    -> STOP
  both touched before the next print     -> STOP (adverse selection)
  neither by session end                 -> FORCE at last price
Costs 0.848% round trip. One position per symbol-day per family.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SNAP_DIR = ROOT / "data" / "snapshots"
DPS_URL = "https://dps.psx.com.pk/timeseries/eod/{sym}"
COST = 0.848
TP = 2.0
SL = -1.0
CACHE = ROOT / "data" / "backtest" / "prior_closes_tick.json"

PKT = timezone(timedelta(hours=5))


def receive_pkt(rec: dict) -> datetime:
    ts = rec.get("receiveTime") or rec.get("requestTime") or rec.get("generatedAt")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc).astimezone(PKT)
    return datetime.fromisoformat(str(ts)).astimezone(PKT)


def load_session(path: Path):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=receive_pkt)
    return rows


def load_prior_closes(symbols, dates_needed):
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    import requests

    out = {}
    http = requests.Session()
    for i, sym in enumerate(sorted(symbols)):
        try:
            r = http.get(DPS_URL.format(sym=sym), timeout=15)
            data = (r.json() or {}).get("data") or []
            out[sym] = {datetime.fromtimestamp(row[0], tz=timezone.utc).date().isoformat(): row[1] for row in data}
        except Exception:
            out[sym] = {}
        if (i + 1) % 100 == 0:
            print(f"  prior closes {i + 1}/{len(symbols)}", flush=True)
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def main():
    files = sorted(SNAP_DIR.glob("*.jsonl.gz"))
    sessions = {}
    all_syms = set()
    for f in files:
        d = f.name.removesuffix(".jsonl.gz")
        rows = load_session(f)
        sessions[d] = rows
        for rec in rows:
            all_syms.update((rec.get("quotes") or {}).keys())
    print(f"sessions: {len(sessions)}, symbols seen: {len(all_syms)}")

    dates_needed = sorted(sessions.keys())
    history = load_prior_closes(all_syms, dates_needed)
    # prior-session close per (sym, date): the last DPS session STRICTLY before d
    prior = {}
    for sym, h in history.items():
        ds = sorted(h.keys())
        for i, dd in enumerate(ds):
            if dd in dates_needed and i > 0:
                prior[(sym, dd)] = h[ds[i - 1]]
    print(f"prior pairs: {len(prior)}")

    # running per-symbol state across each session
    trades = defaultdict(list)
    for d in dates_needed:
        rows = sessions[d]
        st = defaultdict(lambda: {"max_ext": -99.0, "vwap_pv": 0.0, "vol": 0.0,
                                  "below_vwap": False, "running_high": 0.0,
                                  "trig": set()})
        for rec in rows:
            t = receive_pkt(rec)
            minutes = t.hour * 60 + t.minute
            for sym, q in (rec.get("quotes") or {}).items():
                if not q or q.get("status") != "OPN":
                    continue
                price = q.get("price")
                if not price or price <= 0:
                    continue
                pc = prior.get((sym, d))
                if not pc or pc <= 0:
                    continue
                s = st[sym]
                ext = (price / pc - 1) * 100
                s["max_ext"] = max(s["max_ext"], ext)
                s["running_high"] = max(s["running_high"], price)
                vol = q.get("volume") or 0.0
                s["vwap_pv"] += price * max(vol, 0)
                s["vol"] += max(vol, 0)
                if minutes < 90:      # skip the opening 90 min for triggers
                    continue
                vwap = s["vwap_pv"] / s["vol"] if s["vol"] > 0 else None
                bid, ask = q.get("bid"), q.get("ask")
                spread_ok = (bid and ask and price > 0 and (ask - bid) / price < 0.01)
                # EARLY: fresh cross into [+1.5, +2.5] from below
                if ("early" not in s["trig"] and 1.5 <= ext <= 2.5
                        and s["max_ext"] < 3.0 and spread_ok):
                    s["trig"].add("early")
                    trades["early"].append({"sym": sym, "date": d, "entry": price,
                                            "pc": pc, "t": t, "ext": ext})
                # PULLBK: real move, dipping from its high
                if ("pullbk" not in s["trig"] and 2.0 <= ext <= 6.0
                        and s["running_high"] > 0
                        and (s["running_high"] / price - 1) * 100 >= 0.8
                        and spread_ok):
                    s["trig"].add("pullbk")
                    trades["pullbk"].append({"sym": sym, "date": d, "entry": price,
                                             "pc": pc, "t": t, "ext": ext})
                # RECLM: back above VWAP after below
                if vwap and vwap > 0:
                    above = price >= vwap
                    if above and s["below_vwap"] and "reclm" not in s["trig"] and spread_ok:
                        s["trig"].add("reclm")
                        trades["reclm"].append({"sym": sym, "date": d, "entry": price,
                                                "pc": pc, "t": t, "ext": ext})
                    s["below_vwap"] = not above
                # CHASE: the old behavior
                if ("chase" not in s["trig"] and ext >= 4.0 and spread_ok):
                    s["trig"].add("chase")
                    trades["chase"].append({"sym": sym, "date": d, "entry": price,
                                            "pc": pc, "t": t, "ext": ext})
        # resolve all triggers of the day against subsequent prints
        print(f"  {d}: triggers so far " +
              str({fam: len([t for t in tl if t['date'] == d]) for fam, tl in trades.items()}))
        last_price = {}
        for rec in reversed(rows):
            for sym, q in (rec.get("quotes") or {}).items():
                if q and q.get("price"):
                    last_price.setdefault(sym, q["price"])
        highs, lows = {}, {}
        for rec in rows:
            for sym, q in (rec.get("quotes") or {}).items():
                if not q or not q.get("price"):
                    continue
                highs[sym] = max(highs.get(sym, 0.0), q["price"])
                lows[sym] = min(lows.get(sym, 1e18), q["price"])
        for fam, tl in trades.items():
            for tr in tl:
                if tr["date"] != d or "outcome" in tr:
                    continue
                entry = tr["entry"]
                hi, lo, lp = highs.get(tr["sym"]), lows.get(tr["sym"]), last_price.get(tr["sym"])
                if lp is None:
                    tr.update(outcome="NOEXIT", pnl=0.0)
                    continue
                touched_tp = hi is not None and hi >= entry * (1 + TP / 100)
                touched_sl = lo is not None and lo <= entry * (1 + SL / 100)
                if touched_tp and touched_sl:
                    tr.update(outcome="STOP", pnl=SL - COST)
                elif touched_tp:
                    tr.update(outcome="WIN", pnl=TP - COST)
                elif touched_sl:
                    tr.update(outcome="STOP", pnl=SL - COST)
                else:
                    ret = (lp / entry - 1) * 100
                    tr.update(outcome="FORCE", pnl=ret - COST)

    print(f"\n{'family':<8} {'n':>4}  {'win%':>6} {'stop%':>6} {'force%':>7}  {'avg net':>8}  {'total':>8}")
    for fam in ("early", "pullbk", "reclm", "chase"):
        tl = trades.get(fam, [])
        done = [t for t in tl if t.get("outcome") in ("WIN", "STOP", "FORCE")]
        if not done:
            print(f"{fam:<8} {0:>4}")
            continue
        n = len(done)
        w = sum(1 for t in done if t["outcome"] == "WIN")
        s = sum(1 for t in done if t["outcome"] == "STOP")
        f = sum(1 for t in done if t["outcome"] == "FORCE")
        avg = sum(t["pnl"] for t in done) / n
        print(f"{fam:<8} {n:>4}  {100*w/n:>6.1f} {100*s/n:>6.1f} {100*f/n:>7.1f}  {avg:>+8.2f}  {sum(t['pnl'] for t in done):>+8.2f}")

    # per-session robustness for the best family
    print("\nper-session (early):")
    byd = defaultdict(list)
    for t in trades.get("early", []):
        if t.get("outcome") in ("WIN", "STOP", "FORCE"):
            byd[t["date"]].append(t)
    for d in sorted(byd):
        g = byd[d]
        w = sum(1 for t in g if t["outcome"] == "WIN")
        print(f"  {d}: n={len(g):>2} win {100*w/len(g):5.1f}% avg {sum(t['pnl'] for t in g)/len(g):+.2f}%")


if __name__ == "__main__":
    main()
