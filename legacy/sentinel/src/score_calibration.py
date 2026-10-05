"""
Score calibration - the master score as an honest win probability.

THE JOB (the 2026-09-20 diagnostic report, item 4): two calls at raw
score 0.62 and 0.91 are treated identically today. Calibration turns
the score into a measured probability of a winning trade, per band,
from the closed ledger - the difference between "the engine fired"
and "this class of call has won X% of the time".

THE HONESTY RULE: a calibration fit on a thin ledger is a lie with
math on it. This module REFUSES to publish probabilities until
  - at least MIN_TRADES closed trades carry a stamped entry_score,
  - and every published band holds at least MIN_PER_BUCKET trades.
Until then it reports "insufficient" and writes nothing. The entry
score stamp only began with v2.1.0 (2026-09-18), so the ledger needs
real calendar time before this can speak. Nothing here is urgent -
it exists so the plumbing is proven the day the data arrives.

Fit runs daily beside the gate refit (cloud_close_session); outcomes
accumulate, the bands re-measure, and when a band's measured win rate
falls under its breakeven, that is a rulebook problem the refit loop
hears about from the morning report - not something this file fixes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from psx_core import paths  # noqa: E402  (bootstrap after path insert)

# Honesty floors. 45 unlabeled trades exist today; the v2.1.0-stamped
# ledger starts from zero. 60 stamped trades is the smallest sample at
# which per-band rates stop swinging wildly between days; 20 per band
# is the smallest at which a single trade moves the rate by <=5 pts.
MIN_TRADES = 60
MIN_PER_BUCKET = 20

# Score bands. The conviction gate admits from 0.50 up; the Rule 22
# ceiling refuses above 0.70. Bands align to those live boundaries so
# each band is a policy-relevant slice, not an arbitrary decile.
BANDS = (
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-1.00", 0.70, 1.01),
)


def _load_book(book_path: Path | None = None) -> list[dict]:
    p = book_path or paths.PORTFOLIO_FILE
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else (raw.get("trades") or [])
    return [r for r in rows if isinstance(r, dict)]


def _usable(rows: list[dict]) -> list[dict]:
    """One filter path for every source: stamped score, closed, net pnl.

    Applies to injected trades (tests, audits) exactly as to the live
    book, so no caller can accidentally fit on unstamped rows.
    """
    out = []
    for r in rows:
        if r.get("status") != "CLOSED":
            continue
        score = r.get("entry_score")
        net = r.get("pnl_net_pct")
        if score is None or net is None:
            continue
        try:
            float(score), float(net)
        except (TypeError, ValueError):
            continue
        out.append(r)
    return out


def fit(
    trades: list[dict] | None = None,
    *,
    out_path: Path | None = None,
    min_trades: int = MIN_TRADES,
    min_per_bucket: int = MIN_PER_BUCKET,
) -> dict:
    """Measure win rate per score band, or refuse while the ledger is thin.

    Trades may be injected (tests, audits); the default reads the live
    closed book. Nothing is written until the honesty floors pass.
    """
    rows = _usable(trades if trades is not None else _load_book())
    verdict: dict = {
        "trades": len(rows),
        "min_trades": min_trades,
        "bands": [],
    }
    if len(rows) < min_trades:
        verdict["status"] = "insufficient"
        verdict["note"] = (
            f"{len(rows)}/{min_trades} stamped closed trades - "
            "fitting now would be lying with math. Refusing to publish."
        )
        return verdict

    out = []
    for name, lo, hi in BANDS:
        band = [r for r in rows if lo <= float(r["entry_score"]) < hi]
        wins = sum(1 for r in band if float(r["pnl_net_pct"]) > 0)
        entry = {
            "band": name,
            "trades": len(band),
            "wins": wins,
            "win_rate": round(wins / len(band), 4) if band else None,
            "avg_net_pct": (
                round(sum(float(r["pnl_net_pct"]) for r in band) / len(band), 4)
                if band
                else None
            ),
            "reliable": len(band) >= min_per_bucket,
        }
        out.append(entry)
    verdict["bands"] = out
    verdict["status"] = "ok"
    verdict["note"] = (
        "All bands meet the per-band floor."
        if all(b["reliable"] for b in out)
        else "Thin bands are reported but flagged unreliable."
    )

    dest = out_path or (paths.DATA_DIR / "calibration.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    return verdict


def load(cal_path: Path | None = None) -> dict | None:
    """The published calibration, or None while none exists."""
    p = cal_path or (paths.DATA_DIR / "calibration.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    paths.enable_utf8_stdout()
    verdict = fit()
    print(f"score calibration: {verdict['status']} - {verdict['note']}")
    for b in verdict.get("bands", []):
        flag = "" if b["reliable"] else "  [thin - unreliable]"
        print(
            f"  {b['band']}: {b['trades']} trades, "
            f"win {'' if b['win_rate'] is None else format(b['win_rate'], '.1%')}, "
            f"avg net {b['avg_net_pct']}%{flag}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
