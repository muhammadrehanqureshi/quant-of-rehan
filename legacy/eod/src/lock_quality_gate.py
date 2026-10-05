"""Lock-quality gates for the evening pick (grind 8/9, full corpus).

The v2.3 policy (locked >=9.9%, >=500M distribution veto) validated at
+0.42/trade on the full 175-session corpus. Two refinements measured
there improve BOTH halves and ship as hard gates:

  * VOLUME-RATIO CEILING: a lock on >5x its 20-day average volume wins
    materially less (one-way distribution into the circuit, the crowd
    already aboard) - discovery 67.3% vs 64.4%, validation 72.1% vs
    73.9% at equal-or-better net. Grind 8 refinement C.
  * PRIOR-DAY PARTICIPATION FLOOR: a lock on a name that traded a dead
    prior day (<Rs 0.5M) has no follow-through behind it. Grind 8
    refinement A; combined with the ceiling in grind 9 the policy went
    discovery 68.0% (+0.27/t) / validation 78.3% (+0.53/t).

Missing evidence never gates (the veto requires the numbers).
"""
from __future__ import annotations

VOLUME_RATIO_CEIL = 5.0        # 20-day volume multiples on the lock day
PRIOR_DAY_VALUE_FLOOR_PKR = 500_000.0  # Rs on the day BEFORE the lock


def apply_lock_quality(
    picks: list[dict],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Refuse locked-close picks with distribution-shaped volume."""
    kept, blocked = [], []
    for p in picks:
        chg = p.get("change_pct")
        if chg is None or float(chg) < 9.9:
            kept.append(p)  # not this gate's class
            continue
        vsr = p.get("volume_surge")
        if vsr is not None and float(vsr) > VOLUME_RATIO_CEIL:
            blocked.append(
                (
                    p["symbol"],
                    f"lock on {float(vsr):.1f}x 20-day volume - above the "
                    f"{VOLUME_RATIO_CEIL:.0f}x ceiling (one-way distribution "
                    "into the circuit; grind 8 refinement C)",
                )
            )
            continue
        prev_val = p.get("prev_day_value")
        if prev_val is not None and float(prev_val) < PRIOR_DAY_VALUE_FLOOR_PKR:
            blocked.append(
                (
                    p["symbol"],
                    f"prior day traded only Rs {float(prev_val)/1e6:.2f}M - "
                    "no follow-through behind the lock "
                    "(grind 8 refinement A)",
                )
            )
            continue
        kept.append(p)
    return kept, blocked
