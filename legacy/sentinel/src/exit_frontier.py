"""
Exit-policy frontier simulator.

The question it answers: on THIS bot's real entries, on THIS market's
real ticks, which exit policy produces the highest win rate - and what
does each point on the win-rate dial cost in expectancy?

Method: take every recorded entry (live ledger + replay-mined), replay
its symbol's actual tick path from the stored snapshots under a grid of
exit policies (target / stop / trailing activation+width), and record
which barrier hits first. Costs are the REAL PSX account costs (full
fee schedule below, stated by Mr. Rehan 2026-09-13). No synthetic
data, no assumptions about fills beyond the policy itself.

Conservative conventions (chosen so the sim UNDERSTATES performance):
  * a tick that breaches both stop and target in the same print closes
    at the STOP (adverse-selection rule);
  * target fills AT the target price (limit order), stop fills AT the
    breaching tick (market order);
  * if the very first tick after entry already breaches the stop, that
    counts as a stop-out (entry noise goes against us).

Usage:
    python src/exit_frontier.py                # full grid report
    python src/exit_frontier.py --min-win 70   # only combos >= 70% WR
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths  # noqa: E402


# ---------------------------------------------------------------------------
# REAL PSX trading costs (full fee schedule, Mr. Rehan, 2026-09-13)
# ---------------------------------------------------------------------------
# Commission, charged on BOTH the buy and the sell:
#   * price > 20 PKR/share: 0.15% of traded value per side;
#   * price <= 20 PKR/share: 0.03 PKR per share per side (as a % of
#     value this EXPLODES for cheap stocks: ~0.3%/side at 10 PKR,
#     ~0.6%/side at 5 PKR).
# Sindh Sales Tax: 16% OF THE COMMISSION amount (not of trade value).
# Regulatory levies: ~0.05% of traded value per side.
# Capital gains tax: 15% of the profit. Modeled on GROSS profit, which
# OVERSTATES the tax (real CGT allows cost deductions) - the sim stays
# conservative on purpose.

COMMISSION_PCT_FRAC = 0.0015        # 0.15% of traded value (price > 20)
COMMISSION_PER_SHARE_PKR = 0.03     # flat per share (price <= 20)
PRICE_BAND_PKR = 20.0
SST_RATE = 0.16                     # 16% of the commission amount
REGULATORY_LEVY_FRAC = 0.0005       # ~0.05% of traded value, per side
PROFIT_TAX_RATE = 0.15              # capital gains tax on the profit


def _side_cost_pkr(price: float) -> float:
    """One side's commission + SST + levies, in PKR per share."""
    if price > PRICE_BAND_PKR:
        commission = COMMISSION_PCT_FRAC * price
    else:
        commission = COMMISSION_PER_SHARE_PKR
    return commission + SST_RATE * commission + REGULATORY_LEVY_FRAC * price


def _net(entry_price: float, exit_price: float, kind: str) -> tuple[float, str]:
    """Net pnl as % of entry value, after the full PSX cost stack."""
    gross_pkr = exit_price - entry_price
    costs_pkr = _side_cost_pkr(entry_price) + _side_cost_pkr(exit_price)
    tax_pkr = PROFIT_TAX_RATE * max(gross_pkr, 0.0)
    net_pkr = gross_pkr - costs_pkr - tax_pkr
    return net_pkr / entry_price * 100.0, kind


def round_trip_cost_pct(entry_price: float, exit_price: float) -> float:
    """Buy+sell costs as a % of entry value (for scratch marking)."""
    costs_pkr = _side_cost_pkr(entry_price) + _side_cost_pkr(exit_price)
    return costs_pkr / entry_price * 100.0


def net_pnl_pct(entry_price: float, exit_price: float) -> float:
    """Net pnl % after the FULL cost stack (commission both bands, SST,
    levies, CGT) - the truth the paper ledger reports beside the gross
    figure (v0.16.5: the 43-trade ledger was gross; every -2% stop was
    really ~-2.85% net)."""
    net_pct, _kind = _net(entry_price, exit_price, "ledger")
    return net_pct


def breakeven_win_rate(target_pct: float, stop_pct: float,
                       round_trip_pct: float | None = None) -> float:
    """Win rate at which this target/stop pair nets exactly zero.

    win net   = 0.85*target - round-trip costs
    loss net  = -(stop + round-trip costs)

    ``round_trip_pct`` defaults to the >20 PKR band (0.15% commission),
    i.e. 2 * (0.15% * 1.16 + 0.05%) = 0.448% of value.
    """
    if round_trip_pct is None:
        round_trip_pct = (
            2.0 * (COMMISSION_PCT_FRAC * (1.0 + SST_RATE) + REGULATORY_LEVY_FRAC)
            * 100.0
        )
    win_net = (1.0 - PROFIT_TAX_RATE) * target_pct - round_trip_pct
    loss_net = stop_pct + round_trip_pct
    return loss_net / (loss_net + win_net) * 100.0


# ---------------------------------------------------------------------------
# Entry collection
# ---------------------------------------------------------------------------

def collect_entries() -> list[dict]:
    """
    Every entry we hold evidence for: the live ledger's labeled trades
    plus replay-mined virtual trades from logs/mine/*.json artifacts.
    Deduplicated on (date, symbol, minute).
    """
    entries: dict[tuple, dict] = {}

    ledger = paths.DATA_DIR / "outcomes.jsonl"
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("entry_time") or ""
            if not ts:
                continue
            key = (r.get("trading_date"), r.get("symbol"), ts[11:16])
            entries[key] = {
                "date": r.get("trading_date"),
                "symbol": r.get("symbol"),
                "entry_time": ts,
                "source": "ledger",
            }

    for f in sorted((paths.PROJECT_ROOT / "logs" / "mine").glob("*.json")):
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"\[\s*\{.*\]\s*$", raw, re.S)
            reports = json.loads(m.group(0)) if m else []
        except (json.JSONDecodeError, OSError):
            continue
        for rep in reports:
            for t in rep.get("mined_trades", []):
                et = t.get("entry_time") or ""
                if not et or not t.get("symbol"):
                    continue
                # The replay report may not carry a top-level date; the
                # entry timestamp itself is authoritative (UTC ISO).
                rep_date = rep.get("date") or et[:10]
                key = (rep_date, t.get("symbol"), et[11:16])
                entries.setdefault(key, {
                    "date": rep_date,
                    "symbol": t.get("symbol"),
                    "entry_time": et,
                    "source": f"mined:{f.name}",
                })

    return sorted(entries.values(), key=lambda e: (e["date"], e["entry_time"]))


# ---------------------------------------------------------------------------
# Tick paths
# ---------------------------------------------------------------------------

def load_tick_path(date: str, symbol: str, after: str) -> list[tuple[str, float]]:
    """(timestamp, price) ticks for one symbol after a cutoff instant."""
    f = paths.SNAPSHOT_DIR / f"{date}.jsonl.gz"
    if not f.exists():
        return []
    cutoff = after[:19]
    path: list[tuple[str, float]] = []
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = snap.get("generatedAt") or ""
            if ts[:19] < cutoff:
                continue
            q = (snap.get("quotes") or {}).get(symbol)
            if not q:
                continue
            p = q.get("price")
            if isinstance(p, (int, float)) and p > 0:
                path.append((ts, float(p)))
    return path


# ---------------------------------------------------------------------------
# One policy replayed over one path
# ---------------------------------------------------------------------------

def replay_policy(
    path: list[tuple[str, float]],
    entry_price: float,
    *,
    target_pct: float,
    stop_pct: float,
    trail_activation_pct: float,
    trail_pct: float,
    stale_min: int = 0,
    stale_gain_pct: float = 0.3,
) -> tuple[float, str]:
    """(net pnl % after real costs, exit kind) for one policy on one path.

    ``stale_min`` > 0 adds a stale-trade timeout: if the position has not
    gained at least ``stale_gain_pct``% within that many minutes, exit at
    market. Converts slow bleeds into scratches on chop days.
    """
    target_px = entry_price * (1 + target_pct / 100)
    stop_px = entry_price * (1 - stop_pct / 100)
    trailing = None  # ratcheted stop once activated
    t0 = path[0][0][:19] if path else ""

    def _minutes(ts: str) -> float:
        try:
            a = datetime.fromisoformat(t0)
            b = datetime.fromisoformat(ts[:19])
            return (b - a).total_seconds() / 60.0
        except ValueError:
            return 0.0

    for ts, px in path:
        # Trailing ratchet first: activation and upward ratchet only.
        if trail_pct > 0 and px >= entry_price * (1 + trail_activation_pct / 100):
            new_trail = px * (1 - trail_pct / 100)
            trailing = new_trail if trailing is None else max(trailing, new_trail)

        effective_stop = stop_px if trailing is None else max(stop_px, trailing)

        hit_stop = px <= effective_stop
        hit_target = px >= target_px
        if hit_stop and hit_target:
            # Adverse-selection rule: same print does both -> stop.
            return _net(entry_price, effective_stop, "stop")
        if hit_stop:
            return _net(entry_price, effective_stop, "stop")
        if hit_target:
            return _net(entry_price, target_px, "target")
        if stale_min and _minutes(ts) >= stale_min:
            if px < entry_price * (1 + stale_gain_pct / 100):
                return _net(entry_price, px, "stale")

    # Time exit: last tick of the path (session force-close).
    if path:
        return _net(entry_price, path[-1][1], "time")
    return _net(entry_price, entry_price, "no-ticks")


# ---------------------------------------------------------------------------
# Grid report
# ---------------------------------------------------------------------------

# v0.11.0: targets are constrained to Mr. Rehan's tradable band
# (>=2%, <=3%) - below 2% the 0.30% round-trip fee + 15% profit tax
# eat the edge. Trails are tuned for far targets: the trail must be
# reachable (activation below target) and tight enough to lock gains.
TARGETS = [2.0, 2.5, 3.0]
STOPS = [1.0, 1.5, 2.0, 3.0]
TRAILS = [  # (activation, width) - width 0 disables
    (1.0, 0.5), (1.0, 0.75), (1.0, 1.0),
    (1.5, 0.5), (1.5, 0.75), (1.5, 1.0),
    (2.0, 0.75), (2.0, 1.0),
]
STALES = [  # (minutes, gain gate)
    (0, 0.0), (30, 0.3), (45, 0.2), (60, 0.5),
]


def filter_dates(entries: list[dict], dates_csv: str | None) -> list[dict]:
    """Keep only entries on the given dates (the prospective book)."""
    if not dates_csv:
        return entries
    keep = {d.strip() for d in dates_csv.split(",") if d.strip()}
    return [e for e in entries if e["date"] in keep]


def run_grid(entries: list[dict]) -> list[dict]:
    # Pre-extract each entry's tick path once.
    paths_cache: dict[int, list] = {}
    valid: list[dict] = []
    for i, e in enumerate(entries):
        path = load_tick_path(e["date"], e["symbol"], e["entry_time"])
        if len(path) < 5:
            continue
        entry_price = path[0][1]
        paths_cache[i] = (entry_price, path)
        valid.append(e)

    rows = []
    combos = [(t, s, None, None, 0, 0.0) for t in TARGETS for s in STOPS]
    combos += [(t, s, act, w, 0, 0.0)
               for t in TARGETS for s in STOPS for act, w in TRAILS]
    combos += [(t, s, None, None, sm, sg)
               for t in TARGETS for s in STOPS for sm, sg in STALES if sm]
    for target, stop, act, width, stale_m, stale_g in combos:
        results = []
        for i, e in enumerate(valid):
            entry_price, path = paths_cache[i]
            pnl, kind = replay_policy(
                path, entry_price,
                target_pct=target, stop_pct=stop,
                trail_activation_pct=act or 10**9,  # never activates
                trail_pct=width or 0,
                stale_min=stale_m,
                stale_gain_pct=stale_g,
            )
            results.append((pnl, kind))
        wins = sum(1 for p, _ in results if p > 0)
        n = len(results)
        total = sum(p for p, _ in results)
        rows.append({
            "target": target, "stop": stop,
            "trail_act": act, "trail_w": width,
            "stale": stale_m, "stale_g": stale_g,
            "n": n, "wins": wins,
            "win_rate": wins / n * 100 if n else 0.0,
            "avg_pnl": total / n if n else 0.0,
            "total_pnl": total,
        })
    rows.sort(key=lambda r: (-r["win_rate"], -r["avg_pnl"]))
    return rows


def run_detail(entries: list[dict], target: float, stop: float,
               act: float | None, width: float | None,
               stale_min: int = 0, stale_gain: float = 0.0) -> None:
    """Per-trade outcome under one policy, sorted by pnl."""
    rows = []
    for e in entries:
        path = load_tick_path(e["date"], e["symbol"], e["entry_time"])
        if len(path) < 5:
            continue
        entry_price = path[0][1]
        pnl, kind = replay_policy(
            path, entry_price,
            target_pct=target, stop_pct=stop,
            trail_activation_pct=act or 10**9,
            trail_pct=width or 0,
            stale_min=stale_min,
            stale_gain_pct=stale_gain,
        )
        rows.append((pnl, kind, e))
    rows.sort(key=lambda r: r[0])
    stale_txt = f" {stale_min:g}m/{stale_gain:g}%" if stale_min else ""
    print(f"policy tgt={target:g}% stop={stop:g}% "
          f"trail={'' if act is None else f'{act:g}/{width:g}'}{stale_txt} "
          f"(net of full PSX costs: commission+SST+levies, 15% CGT)")
    for pnl, kind, e in rows:
        # W = net win; F = negative but a scratch/soft exit (stale or
        # time), L = a full stop-out loss.
        mark = "W" if pnl > 0 else ("F" if kind in ("stale", "time", "no-ticks") else "L")
        print(f"  {mark}  {e['date']} {e['symbol']:7s} "
              f"{e['entry_time'][11:19]}  {pnl:+6.2f}%  ({kind})")
    wins = sum(1 for p, _, _ in rows if p > 0)
    n = len(rows)
    if n:
        print(f"  => {wins}W/{n-wins}L ({wins/n*100:.0f}%), "
              f"avg {sum(p for p, _, _ in rows)/n:+.2f}%, "
              f"total {sum(p for p, _, _ in rows):+.2f}%")


def main(argv=None) -> int:
    paths.enable_utf8_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-win", type=float, default=None,
                        help="only show combos with win rate >= this")
    parser.add_argument("--dates", default=None,
                        help="comma-separated dates to study (default: all)")
    parser.add_argument("--detail", default=None,
                        help="per-trade detail for one policy: TGT,STOP[,ACT,WIDTH[,STALE_MIN,STALE_GAIN]]")
    args = parser.parse_args(argv)

    entries = filter_dates(collect_entries(), args.dates)
    print(f"entries under study: {len(entries)}")
    for e in entries:
        print(f"  {e['date']} {e['symbol']:7s} {e['entry_time'][11:19]} ({e['source']})")
    if args.detail:
        parts = [float(p) for p in args.detail.split(",")]
        target, stop = parts[0], parts[1]
        act = parts[2] if len(parts) > 2 else None
        width = parts[3] if len(parts) > 3 else None
        stale_m = int(parts[4]) if len(parts) > 4 else 0
        stale_g = parts[5] if len(parts) > 5 else 0.0
        run_detail(entries, target, stop, act, width, stale_m, stale_g)
        return 0

    if len(entries) < 5:
        print("Not enough entries for a frontier - run more sessions.")
        return 1

    rows = run_grid(entries)

    print()
    hdr = (f"{'tgt%':>5} {'stp%':>5} {'trail':>9} {'stale':>10} | {'W/L':>6} "
           f"{'win%':>6} {'avg%':>7} {'tot%':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if args.min_win and r["win_rate"] < args.min_win:
            continue
        trail = (f"{r['trail_act']:g}/{r['trail_w']:g}"
                 if r["trail_act"] else "-")
        stale = (f"{r['stale']:g}m/{r['stale_g']:g}%"
                 if r["stale"] else "-")
        print(f"{r['target']:>5g} {r['stop']:>5g} {trail:>9} {stale:>10} | "
              f"{r['wins']}W/{r['n']-r['wins']}L "
              f"{r['win_rate']:>6.0f} {r['avg_pnl']:>+7.2f} "
              f"{r['total_pnl']:>+7.2f}")

    print("\nbreakeven win rates - stocks >20 PKR "
          "(0.15%/side commission, full cost stack):")
    for t in TARGETS:
        for s in STOPS:
            print(f"  tgt {t:g}% / stop {s:g}%  ->  "
                  f"{breakeven_win_rate(t, s):.0f}% of trades must win")
    # Cheap stocks pay 0.03 PKR/share per side - as a % of value this
    # scales inversely with price. Show the pain at a representative
    # price so nobody day-trades penny prints blind.
    for px in (10.0, 5.0):
        c = 2.0 * (COMMISSION_PER_SHARE_PKR * (1.0 + SST_RATE)
                   + REGULATORY_LEVY_FRAC * px) / px * 100.0
        print(f"  [band <=20 PKR, e.g. {px:g} PKR stock: round trip "
              f"{c:.2f}% - tgt 2/stop 1.5 needs "
              f"{breakeven_win_rate(2.0, 1.5, c):.0f}% WR]")

    for t, s in ((2.0, 1.5), (3.0, 1.5)):
        c = [r for r in rows if r["target"] == t and r["stop"] == s
             and r["trail_act"] is None and not r["stale"]]
        if c:
            c = c[0]
            print(f"reference (tgt {t:g}/stop {s:g}, no trail): "
                  f"{c['wins']}W/{c['n']-c['wins']}L, "
                  f"win rate {c['win_rate']:.0f}%, avg {c['avg_pnl']:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
