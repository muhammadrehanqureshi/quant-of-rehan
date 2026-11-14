"""Run the strategies over the data. One shard of the work, one process, one core.

    python -m kmiall100.run --data data --out results/shard0 --shard 0/4

Runs only in the cloud (see guard.py). The loop is built to stay small:

* the unit of work is one (timeframe, symbol) series: it is loaded, turned into
  one ``Ctx``, every strategy that applies is run on it (sharing the indicator
  cache), the trades are cut down to compact arrays, and the series is freed;
* trades are kept as 17 bytes each, so even a big shard stays far below a gigabyte;
* a strategy that raises is logged and skipped, it never stops the shard;
* ``--time-budget-min`` stops starting new series when the job is close to its
  limit and says so in meta.json, so a partial run is never mistaken for a full one.
"""

from __future__ import annotations

import argparse
import gc
import gzip
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import guard

MODE = guard.require_cloud()           # exits with code 3 when run on a normal PC
guard.pin_threads(1)

import numpy as np                      # noqa: E402  (after the thread pins on purpose)
import pandas as pd                     # noqa: E402

from . import __version__, data as D, engine as E, metrics as M   # noqa: E402
from .core import ALL_TFS, BPD, Ctx, Frame, REGISTRY               # noqa: E402
from .strategies import REGISTRY as _R                              # noqa: E402,F401

DEFAULT_HOLD = {"5m": 36, "15m": 24, "30m": 14, "1h": 7, "1d": 5}
PROFILES = ("law", "atr", "trail")
DAYLOW_PROFILE = "daylow"
SWING_PROFILES = ("swing", "swingatr", "swingtrail")
ALL_PROFILES = PROFILES + (DAYLOW_PROFILE,) + SWING_PROFILES
SWING_HOLD = 30                 # daily bars, about six trading weeks
NO_TP = 10.0


def parse_shard(s: str) -> Tuple[int, int]:
    a, b = s.split("/")
    i, n = int(a), int(b)
    if not (0 <= i < n):
        raise SystemExit("--shard must look like i/N with 0 <= i < N")
    return i, n


def pick_strategies(ids: Optional[str], shard: Tuple[int, int]) -> List[str]:
    allids = sorted(REGISTRY)
    if ids:
        want = [s.strip().upper() for s in ids.split(",") if s.strip()]
        bad = [s for s in want if s not in REGISTRY]
        if bad:
            raise SystemExit("unknown strategy id(s): " + ", ".join(bad))
        allids = want
    i, n = shard
    return [s for k, s in enumerate(allids) if k % n == i]


def profile_arrays(name: str, sig: np.ndarray, x: Ctx, o: np.ndarray | None = None):
    """Per signal take profit, stop and trail fractions for one exit profile."""
    m = len(sig)
    if name == "law":
        return np.full(m, 0.02), np.full(m, 0.01), np.zeros(m)
    if name == "daylow":
        # The stop is the session low known at the signal bar, expressed as a
        # fraction of the next bar's open plus the engine's entry slippage.
        # The final low of the day is never used.
        if o is None:
            raise ValueError("daylow needs the open prices")
        ep = np.full(m, np.nan)
        nxt = sig + 1
        valid = nxt < len(x.c)
        ep[valid] = o[nxt[valid]] * (1.0 + E.SLIP_SIDE)
        low = x.day_lo_sofar()[sig]
        with np.errstate(divide="ignore", invalid="ignore"):
            sl = 1.0 - low / ep
        return np.full(m, 0.012), sl, np.zeros(m)
    if name == "swing":
        return np.full(m, 0.10), np.full(m, 0.05), np.zeros(m)
    atrp = x.atrp()[sig]
    atrp = np.where(np.isfinite(atrp), atrp, 0.01)
    if name == "atr":
        sl = np.clip(1.5 * atrp, 0.004, 0.04)
        return 2.0 * sl, sl, np.zeros(m)
    if name == "swingatr":
        sl = np.clip(2.5 * atrp, 0.015, 0.08)
        return 3.0 * sl, sl, np.zeros(m)
    if name == "swingtrail":
        tr = np.clip(3.0 * atrp, 0.015, 0.10)
        return np.full(m, NO_TP), tr, tr
    tr = np.clip(2.5 * atrp, 0.004, 0.06)
    return np.full(m, NO_TP), tr, tr


def hold_for(s, tf: str, profile: str | None = None) -> int:
    if profile in SWING_PROFILES:
        return SWING_HOLD
    if s.hold and tf in s.hold:
        return int(s.hold[tf])
    if s.overnight:
        return DEFAULT_HOLD[tf] * 3
    return DEFAULT_HOLD[tf]


class Acc:
    """Compact trade store per combination key."""

    def __init__(self):
        self.ts: List[np.ndarray] = []
        self.sym: List[np.ndarray] = []
        self.net: List[np.ndarray] = []
        self.out: List[np.ndarray] = []
        self.bars: List[np.ndarray] = []
        self.gross_sum = 0.0

    def add(self, ts, sym, net, out, bars):
        self.ts.append(ts); self.sym.append(sym); self.net.append(net.astype(np.float32))
        self.out.append(out.astype(np.int8)); self.bars.append(bars.astype(np.int16))

    def cat(self):
        if not self.ts:
            e = np.empty(0)
            return e.astype("int64"), e.astype("int16"), e.astype("float32"), e.astype("int8"), e.astype("int16")
        return (np.concatenate(self.ts), np.concatenate(self.sym), np.concatenate(self.net),
                np.concatenate(self.out), np.concatenate(self.bars))


def variants_for(s, use_grid: bool):
    yield "base", s.params
    if use_grid:
        for k, g in enumerate(s.grid, 1):
            p = dict(s.params)
            p.update(g)
            yield f"g{k}", p


def run_series(tf: str, sym: str, sid_num: int, df: pd.DataFrame, idx_df: Optional[pd.DataFrame], strategies,
               profiles, use_grid: bool, acc: Dict[tuple, Acc], errs: List[str], counts: Dict[str, int]):
    ts = df.index.to_numpy(dtype="datetime64[ns]")
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    if len(c) < 300:
        counts["short_series"] += 1
        return
    ix = None
    if idx_df is not None:
        a = D.align_index(ts, idx_df)
        if a is not None:
            ix = Frame(a["open"].to_numpy(), a["high"].to_numpy(), a["low"].to_numpy(), a["close"].to_numpy(),
                       a["volume"].to_numpy())
    x = Ctx(ts, o, h, l, c, v, tf, ix)
    bad = E.jump_mask(c)
    counts["bars"] += len(c)
    dummy = np.zeros(len(c), dtype=bool)
    ts_i = ts.astype("int64")
    for s in strategies:
        if tf not in s.tfs:
            continue
        if s.needs_index and ix is None:
            counts["skipped_no_index"] += 1
            continue
        flat_eod = x.intraday and not s.overnight
        for vname, params in variants_for(s, use_grid):
            try:
                sig = np.asarray(s.fn(x, **params), dtype=bool)
                if sig.shape != (len(c),):
                    raise ValueError(f"signal shape {sig.shape}")
            except Exception:
                errs.append(f"{s.id} {tf} {sym} {vname}: " + traceback.format_exc(limit=3).replace("\n", " | "))
                continue
            sig = sig & ~bad
            if flat_eod:
                sig = sig & ~x.is_eod                 # a signal on the last bar of the day would enter tomorrow
            idx = np.flatnonzero(sig).astype(np.int64)
            if len(idx) == 0:
                continue
            for pf in profiles:
                tp_f, sl_f, tr_f = profile_arrays(pf, idx, x, o)
                ok = np.isfinite(sl_f) & (sl_f > 0)
                ii, tpf, slf, trf = idx[ok], tp_f[ok], sl_f[ok], tr_f[ok]
                if len(ii) == 0:
                    continue
                mh = hold_for(s, tf, pf)
                _, en, ex, epx, xpx, out, _, _ = E.simulate(o, h, l, c, v, x.is_eod, ii, tpf, slf, trf, mh,
                                                            flat_eod, dummy, False, E.SLIP_SIDE)
                if len(en) == 0:
                    continue
                _, net = E.net_returns(epx, xpx)
                key = (s.id, tf, vname, pf)
                a = acc.get(key)
                if a is None:
                    a = acc[key] = Acc()
                a.add(ts_i[en], np.full(len(en), sid_num, dtype=np.int16), net, out, ex - en + 1)
                counts["trades"] += len(en)


def load_all(root: str, tfs, only_syms, index_name, rep):
    """List (tf, symbol, path/source) and find the index series per timeframe."""
    srcs = [s for s in D.discover(root) if s.tf in tfs]
    return srcs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="folder with the OHLCV files")
    ap.add_argument("--out", required=True, help="folder for this shard's results")
    ap.add_argument("--tfs", default=",".join(ALL_TFS), help="comma list of 5m,15m,30m,1h,1d")
    ap.add_argument("--shard", default="0/1", help="i/N, this job takes every Nth strategy")
    ap.add_argument("--strategies", default="", help="comma list of ids, default all")
    ap.add_argument("--profiles", default=",".join(PROFILES),
                    help="law (TP 2 pct, SL 1 pct), atr, trail, daylow (TP 1.2 pct, SL today's low), "
                         "swing (TP 10 pct, SL 5 pct), swingatr, swingtrail")
    ap.add_argument("--grid", action="store_true", help="also run each strategy's parameter variants")
    ap.add_argument("--symbols", default="", help="comma list, default every file found")
    ap.add_argument("--index", default="", help="index symbol name, default the one that looks like KMIALL")
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--time-budget-min", type=float, default=0.0, help="stop starting new series after this many minutes")
    ap.add_argument("--cpu-cap", type=float, default=0.05, help="only for a deliberate local run: CPU fraction cap")
    a = ap.parse_args(argv)

    t_start = time.time()
    throttle = guard.Throttle(a.cpu_cap) if MODE == "local" else None
    shard = parse_shard(a.shard)
    tfs = [t for t in a.tfs.split(",") if t in ALL_TFS]
    profiles = [p for p in a.profiles.split(",") if p in ALL_PROFILES]
    if not tfs or not profiles:
        raise SystemExit("nothing to run: check --tfs and --profiles")
    if any(p in SWING_PROFILES for p in profiles):
        if set(tfs) != {"1d"}:
            raise SystemExit("swing profiles hold for weeks, so they run on 1d alone")
        if len(profiles) != sum(p in SWING_PROFILES for p in profiles):
            raise SystemExit("swing profiles cannot be mixed with intraday profiles")
    if DAYLOW_PROFILE in profiles and "1d" in tfs:
        raise SystemExit("daylow uses the session low, so it runs on intraday timeframes only")
    ids = pick_strategies(a.strategies, shard)
    strategies = [REGISTRY[i] for i in ids]
    only = {s.strip().upper() for s in a.symbols.split(",") if s.strip()} or None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    srcs = [s for s in D.discover(a.data) if s.tf in tfs]
    if not srcs:
        raise SystemExit(f"no data files found under {a.data}")
    print(f"[kmiall100 {__version__}] mode={MODE} shard={a.shard} strategies={len(ids)} tfs={tfs} profiles={profiles} "
          f"grid={a.grid} sources={len(srcs)}", flush=True)
    if any(p in SWING_PROFILES for p in profiles):
        print(f"swing profiles: {', '.join(p for p in profiles if p in SWING_PROFILES)}, max hold {SWING_HOLD} daily bars",
              flush=True)

    acc: Dict[tuple, Acc] = {}
    errs: List[str] = []
    counts = defaultdict(int)
    reports: Dict[str, dict] = {}
    sym_ids: Dict[str, int] = {}
    days_seen: Dict[str, set] = defaultdict(set)
    partial = False

    # the index series first, per timeframe
    idx_by_tf: Dict[str, pd.DataFrame] = {}
    for src in srcs:
        if src.symbol is not None and not D.is_index(src.symbol, a.index or None):
            continue                                   # a plain stock file, no need to read it twice
        for sym, df, rep in D.load_series(src, None):
            if D.is_index(sym, a.index or None):
                idx_by_tf[src.tf] = df
    if not idx_by_tf:
        print("note: no KMIALL index series found, the 8 index strategies (S079 to S086) will be skipped", flush=True)

    units_done = 0
    units_total = 0
    for tf in tfs:
        for src in [s for s in srcs if s.tf == tf]:
            if a.time_budget_min and (time.time() - t_start) / 60.0 > a.time_budget_min:
                partial = True
                break
            if src.symbol is not None and (D.is_index(src.symbol, a.index or None)
                                           or (only and src.symbol.upper() not in only)):
                continue
            for sym, df, rep in D.load_series(src, None):
                if D.is_index(sym, a.index or None):
                    continue
                if only and sym.upper() not in only:
                    continue
                units_total += 1
                if a.time_budget_min and (time.time() - t_start) / 60.0 > a.time_budget_min:
                    partial = True
                    continue
                sid_num = sym_ids.setdefault(sym, len(sym_ids))
                reports[f"{tf}/{sym}"] = dict(rows_in=rep.rows_in, rows_out=rep.rows_out, dropped=rep.dropped,
                                              ragged=rep.repaired_ragged)
                days_seen[tf].update(np.unique(df.index.to_numpy(dtype="datetime64[D]")).astype("int64").tolist())
                run_series(tf, sym, sid_num, df, idx_by_tf.get(tf), strategies, profiles, a.grid, acc, errs, counts)
                units_done += 1
                del df
                gc.collect()
                if throttle:
                    throttle.checkpoint()
        if partial:
            break
        print(f"  {tf} done: series={units_done} trades={counts['trades']:,} elapsed={(time.time() - t_start) / 60:.1f} min",
              flush=True)

    # ---- metrics per combination
    inv_sym = {v: k for k, v in sym_ids.items()}
    rows = []
    keep: Dict[tuple, tuple] = {}
    for key, a_ in sorted(acc.items()):
        sid, tf, vname, pf = key
        ts, sy, net, oc, br = a_.cat()
        r = M.summarize(ts, sy, net.astype(float), oc, br, len(days_seen[tf]), a.min_trades)
        s = REGISTRY[sid]
        params = s.params if vname == "base" else dict(s.params, **s.grid[int(vname[1:]) - 1])
        r.update(id=sid, name=s.name, family=s.family, tf=tf, variant=vname, profile=pf,
                 params=json.dumps(params, sort_keys=True), overnight=int(s.overnight))
        rows.append(r)
        if r["passes"]:
            keep[key] = (ts, sy, net, oc, br)
    cols = ["id", "name", "family", "tf", "variant", "profile"] + M.FIELDS + ["overnight", "params"]
    df_out = pd.DataFrame(rows, columns=cols)
    df_out.to_csv(out / "summary.csv", index=False, float_format="%.5g")

    if keep:
        names = ["SIGNAL", "TP", "SL", "TIME", "EOD", "GAP_SL"]
        with gzip.open(out / "trades_passing.csv.gz", "wt") as f:
            f.write("id,tf,variant,profile,symbol,entry_time,net_pct,outcome,bars\n")
            for (sid, tf, vname, pf), (ts, sy, net, oc, br) in keep.items():
                tt = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M")
                for k in range(len(ts)):
                    f.write(f"{sid},{tf},{vname},{pf},{inv_sym[int(sy[k])]},{tt[k]},{net[k] * 100:.4f},{E.OUT_NAMES[int(oc[k])]},{int(br[k])}\n")

    (out / "errors.txt").write_text("\n".join(errs[:2000]) + ("\n" if errs else ""))
    meta = dict(version=__version__, mode=MODE, shard=a.shard, strategies=ids, tfs=tfs, profiles=profiles, grid=a.grid,
                units_done=units_done, units_total=units_total, partial=partial, counts=dict(counts),
                errors=len(errs), minutes=round((time.time() - t_start) / 60.0, 2), symbols=len(sym_ids),
                trading_days={k: len(v) for k, v in days_seen.items()}, index_found=sorted(idx_by_tf),
                data_reports=reports)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"[kmiall100] done: combos={len(rows)} trades={counts['trades']:,} errors={len(errs)} "
          f"passing={int(df_out['passes'].fillna(0).sum()) if len(df_out) else 0} partial={partial} "
          f"minutes={meta['minutes']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
