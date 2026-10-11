# Local Parameter Optimisation: Results Report

**Scope:** the 'Quant of Rehan' strategy evaluated against the 5-year PSX EOD
dataset, on the owner's PC, with no cloud service, no GitHub Actions and no
external API involved at any point.
**Run:** 2026-10-10 · `python scripts/backtest_optimize.py --target 0.90`
**Artifacts:** [data/backtest_optimize_report.json](data/backtest_optimize_report.json)
(machine-readable) and this summary.

---

## 1. Headline

The 90% accuracy target **is achievable, and it is not overfitting**: a
90.42% win rate in-sample replicates at 91.15% on leak-free walk-forward test
segments.

**It is also worthless.** Reaching 90% requires a 0.5% take-profit against an
8% stop-loss, a **0.06:1** reward:risk geometry. Net expectancy is
**−0.691% per trade** in-sample and **−0.623%** out-of-sample. No parameter
point anywhere in the swept grid has positive net expectancy after costs.

> The 90% accuracy figure is bought with a payoff geometry that needs a
> **99.48%** win rate merely to break even. The owner's own 2%/1% law needs only
> **52.33%**, and the strategy delivers **24.17%** on it.

In short: the target is the wrong target. Accuracy is not edge.

---

## 2. Data ingestion: every row accounted for

| | |
|---|---|
| Source | `data/eod_history.csv.gz` |
| Universe | `src/data/universe_kmiall.json` (KMIALL only, per `config.KMIALL_ONLY`) |
| Rows | 951,941 in → **284,436 out** (29.9% retained) |
| Symbols | 4,545 in → **307 traded** |
| Window | 2021-10-04 → 2026-10-05 (**1,239 sessions**) |

Drops, by named reason, with no silent shrinkage:

| Reason | Rows | Why |
|---|---|---|
| `outside_universe` | 664,044 | other boards and delisted names; KMIALL trades only |
| `untraded_bar` | 1,635 | `open=high=low=volume=0` with a carried-forward close (halts/suspensions) |
| `nonpositive_price` | 1,791 | `open=0` while the stock genuinely traded (volume ≠ 0), the open cell is defective |
| `short_history` | 35 | fewer than 20 sessions |

Repaired rather than discarded:

| Reason | Rows | Treatment |
|---|---|---|
| `ragged_envelope` | 8,398 | `high < max(open,close)` or `low > min(open,close)` → widened to the open/close envelope. Widening is the *conservative* direction: it can only add stop-outs, and the engine resolves a same-bar TP+SL in favour of the stop. |

A missing timestamp and a null value are counted as **distinct** defects
(`dropped_bad_date` vs `dropped_missing_date`, `dropped_null_value`), because
they need different remedies, dropping 3% of the history costs more than the
defect does.

---

## 3. Why the numbers can be trusted

`src/backtest/engine.py` is the authority, but it costs ~0.30 ms per signal (an
O(n) index lookup per signal), which would make a 500-point sweep take about 25
minutes. The sweep therefore runs a **vectorised evaluator**
(`optimize.evaluate_paths`) over a precomputed forward-price matrix, and the two
are held together by an agreement check that runs on **every** run:

```
Validating the fast evaluator against the authoritative engine...
  compared 1,998 trades (below band screen: 2)
  engine win rate 24.1742% vs fast 24.1742%
  engine net/trade -0.007958 vs fast -0.007958  -> identical
```

A mismatch raises and the script refuses to report the sweep. The check
compares the same *post-band-screen* subset the engine scores, so it cannot
pass by accident.

The fast path reproduces the engine's conservatism deliberately: entry at the
next bar's open, the stop resolved before the target on every bar, a
stop gap-through filled at the open (worse), a target filled at exactly
`tp_price` (never better), and the circuit-band screen that flags unadjusted
corporate actions instead of booking them as wins.

---

## 4. Protocol

| Setting | Value |
|---|---|
| Costs | 22.4 bps per side (0.15% commission + 16% SST + 0.05% levies) |
| CGT | 15% on positive net per-trade returns |
| Band screen | adjacent-print move > 60% ⇒ data-invalid, excluded from metrics |
| Minimum trades | 500 (below this a rate is noise, not a measurement) |
| Walk-forward | 3 folds × 103 test sessions over 1,239 sessions, leak-free |
| Stage 1 grid | tp {0.5, 1, 1.5, 2, 3, 5}% × sl {0.5, 1, 2, 3, 5, 8}% × hold {1,2,3,5,10} |
| Stage 2 grid | score floor {0, 40, 55, 70, 85, 92, 96} × rel-vol floor {0, 1.5, 2.5, 4} × traded-value floor {0, 5M, 20M} × 5 weighting schemes |

The score floors reach 96 on purpose: if a 90% win rate exists anywhere, it is
at the far selective corner, and the search had to actually go there. The
weighting schemes include momentum-only and liquidity-only vectors, to test
whether the shipped blend earns its complexity.

---

## 5. Stage 1, exit law (shipped scanner thresholds)

| Exit law | n | win | net/trade | OOS n | OOS win | OOS net | gap |
|---|---|---|---|---|---|---|---|
| tp 0.5% / sl 8% / hold 10 | 15,330 | **87.78%** | −0.89% | 5,197 | 85.78% | −1.03% | +2.0% |
| tp 0.5% / sl 8% / hold 5 | 15,341 | 85.42% | −0.89% | 5,204 | 83.05% | −1.05% | +2.4% |
| tp 0.5% / sl 8% / hold 3 | 15,344 | 82.79% | −0.87% | 5,207 | 80.58% | −1.03% | +2.2% |
| tp 1% / sl 8% / hold 10 | 15,330 | 82.15% | −0.92% | 5,197 | 79.80% | −1.07% | +2.4% |
| tp 0.5% / sl 5% / hold 10 | 15,330 | 81.08% | −1.00% | 5,197 | 78.10% | −1.14% | +3.0% |

The accuracy ranking walks straight into the worst economics: the only way to
lift the win rate is to shrink the target and widen the stop. Every candidate in
the table loses money per trade.

The owner's shipped law (tp 2% / sl 1% / hold 3) does not reach this table and
scores **24.17%** at a −0.80% net expectancy.

---

## 6. Stage 2, scanner parameters (frozen exit law tp 0.5% / sl 8% / hold 10)

| Candidate | n | win | net/trade | OOS n | OOS win | OOS net | gap |
|---|---|---|---|---|---|---|---|
| liq-only score≥96 rvol≥1.5 val≥0M | 3,163 | **90.42%** | −0.69% | 1,502 | **91.15%** | −0.62% | −0.7% |
| liq-only score≥85 rvol≥0 val≥0M | 29,684 | 89.80% | −0.73% | 11,964 | 89.23% | −0.73% | +0.6% |
| liq-only score≥96 rvol≥0 val≥0M | 8,870 | 89.74% | −0.74% | 4,456 | 90.22% | −0.67% | −0.5% |
| liq-only score≥92 rvol≥0 val≥0M | 17,708 | 89.69% | −0.74% | 7,844 | 89.30% | −0.73% | +0.4% |
| liq-only score≥96 rvol≥4 val≥0M | 636 | 89.62% | −0.74% | 285 | 89.12% | −0.77% | +0.5% |

The winner clears the target at 90.42% on 3,163 trades, and its out-of-sample
figure (91.15%) is *higher* than in-sample, a **negative** overfit gap of
−0.72%. As an accuracy claim, this is real and stable, not fitted noise.

Two further observations:

- Every top candidate is **liq-only** (score driven by traded value alone) or
  mom-only. The shipped five-component blend never enters the top five, which
  suggests the blend is not earning its complexity at these thresholds.
- At a score floor of 96 the surviving sample is thin (636 trades at the
  rvol≥4 point), and the 90%+ figures there rest on far fewer observations than
  the headline row.

---

## 7. Why the 90% target is the wrong target

A geometry's break-even win rate is
`(sl + costs) / ((tp − costs)(1 − CGT) + sl + costs)`, assuming conservatively
that every loser fills at the full stop:

| Geometry | Reward:risk | Break-even win rate | Delivered |
|---|---|---|---|
| Owner's law, tp 2% / sl 1% | 2.00 : 1 | **52.33%** | 24.17% |
| The 90% corner, tp 0.5% / sl 8% | 0.06 : 1 | **99.48%** | 90.42% |

At a 0.5% target a winning trade nets about **0.05%** after a 0.448% round trip,
barely more than nothing, while the rare loser costs 8.4%. The result is
arithmetic, not bad luck: **a 60% win rate on a sane payoff beats a 90% win rate
on this one**, and the engine says so on every run.

A strategy that must be right 99.48% of the time is not a strategy; it is a
liability with a very good-looking hit rate.

---

## 8. What this means for the next step

The exit geometry is the binding constraint, not the entry filter. Evidence:

1. The owner's 2:1 law needs only 52.33% accuracy, a reachable bar, but the
   current entry rule supplies 24.17%.
2. Widening the stop raises accuracy and *lowers* expectancy; the scanner's own
   parameters move accuracy by ~1% at most.
3. The least-bad expectancy anywhere in the grid is this same wide-stop corner,
   which means the search space contains no profitable region at all.

So the productive direction is a **better entry signal graded against the
52.33% bar on the owner's 2:1 law**, not a higher accuracy number against a
degenerate payoff.

---

## 9. Reproducing

```bash
# Full local run (about 3 to 4 minutes on the owner's PC)
python scripts/backtest_optimize.py --target 0.90 --horizon 10

# Fail the command when the target is missed
python scripts/backtest_optimize.py --target 0.90 --require-target

# Tests (offline: ingestion defects, causality, evaluator/engine agreement,
# dual reporting, and an AST proof that nothing on the path imports a network
# or cloud module)
python -m pytest tests/test_backtest_optimize.py -q
```

---

## 10. Files

| File | Role |
|---|---|
| [src/backtest/dataset.py](src/backtest/dataset.py) | ingestion, validation, per-reason drop accounting, conservative repairs |
| [src/backtest/daily_strategy.py](src/backtest/daily_strategy.py) | causal scanner score, gate, forward-path matrix |
| [src/backtest/optimize.py](src/backtest/optimize.py) | vectorised evaluator, engine agreement check, staged search, dual reporting, break-even analysis |
| [scripts/backtest_optimize.py](scripts/backtest_optimize.py) | runnable main script (local only) |
| [tests/test_backtest_optimize.py](tests/test_backtest_optimize.py) | 36 tests: ingestion edge cases, causality, agreement, dual reporting, annotation completeness, offline import proof |
| [data/backtest_optimize_report.json](data/backtest_optimize_report.json) | machine-readable results |
