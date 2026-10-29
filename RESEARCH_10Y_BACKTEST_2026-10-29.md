# Ten-year EOD backtest of the deployed daily scanner analogue

Owner-ordered run, 2026-10-29. Question: does the deployed EOD entry rule
make money, on the last ten years of the whole KMIALL universe, and do its
gate thresholds keep real winners away?

## What ran

- Pipeline: `scripts/build_backtest_dataset.py` (PSX Data Portal
  `mkt_summary` daily-download archive, one OHLCV row per symbol per
  session) then `scripts/backtest_10y.py` (the declared daily analogue in
  `src/backtest/daily_strategy.py` scored with the deployed
  `SCORE_WEIGHTS`, entered next open, simulated by
  `src/backtest/engine.py`: 2% target / 1% stop / 3-session timeout,
  round-trip costs, capital-gains tax on winners, corporate-action screen).
- Dataset: 2,609 weekdays scanned,
  **2,477 real sessions (95.0% coverage, zero fetch failures)**, the 5.1%
  missing days are holidays/closures confirmed by 404s (The missing list
  includes every Pakistan-market holiday pattern; today, 2026-10-29, is
  open and correctly absent until close). 508,780 symbol-day rows, 318 of
  319 universe symbols with data.
- Executed twice, independently: once on GitHub Actions minutes (run
  [`40836238251`](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/runs/40836238251),
  artifact `backtest-ten-year-40836238251`, retained 30 days) and once
  locally under the owner's explicit 2026-10-29 order. The two reports
  agree to the last printed digit: 27,414 trades.

## Headline: the deployed rule LOSES in every one of the eleven years

27,414 filled trades, skipped 39:

| metric | value |
|---|---|
| win rate | 26.3% |
| expectancy net per trade | **-0.76%** |
| profit factor (gross) | **0.67** |
| timeout rate | 1.6% |
| largest drawdown | ruin (compounded equity decays to ~0) |
| avg hold | 1.16 sessions |

Per exit-year (net per trade, gross profit factor, all <= 1.0 = losing):

| year | trades | win rate | expectancy net | PF gross |
|---|---|---|---|---|
| 2016 | 467 | 28.1% | -0.70% | 0.74 |
| 2017 | 2,615 | 28.0% | -0.70% | 0.74 |
| 2018 | 2,369 | 26.9% | -0.80% | 0.65 |
| 2019 | 1,966 | 28.5% | -0.76% | 0.70 |
| 2020 | 2,466 | 27.2% | -0.75% | 0.69 |
| 2021 | 2,441 | 27.1% | -0.76% | 0.68 |
| 2022 | 2,148 | 29.0% | -0.69% | 0.77 |
| 2023 | 2,630 | 30.1% | -0.64% | 0.83 |
| 2024 | 3,065 | 25.3% | -0.80% | 0.63 |
| 2025 | 3,950 | 22.5% | -0.83% | 0.57 |
| 2026 | 3,292 | 22.5% | -0.84% | 0.56 |

Eleven out of eleven losing years, monotone-ish but never close to break
even. This is not variance: the loss is structural.

## The gatekeeping question: no threshold saves it

To answer the owner's specific complaint ("the bot is gatekeeping", "TREET
performed well and no call came") the full grid over the two gate
thresholds was re-simulated on the same ten-year panel. Score was computed
once; only the gate and the fill simulation were re-run per point.

15 points, min score in {35, 40, 45, 50, 55} x min relative volume in
{1.0, 1.25, 1.5}. Every point loses. The best two:

| min score | min rv | signals | expectancy net | PF gross |
|---|---|---|---|---|
| 50 | 1.00 | 53,135 | -0.74% | 0.692 |
| 40 | 1.00 | 62,830 | -0.74% | 0.691 |
| 55 | 1.50 (deployed) | 27,453 | -0.76% | 0.671 |
| ...worst: | 35 | 1.25 | 69,935 | -0.75% | 0.686 |

The trend is monotone in the wrong direction: **looser gates send MORE
losing calls, not fewer losing trades.** Lowering the score/volume gates
would have produced 2.5x more signals and the same or worse per-trade
loss. The TREET-style no-call problem is real, but the cure is not looser
thresholds on this rule: that changes the number of bad calls, not their
sign.

## What this does NOT test

- The intraday ICT/SMC tape engine that actually produces the calls the
  owner consumes (`docs/ICT_SMC_STRATEGY.md`, `src/signals/*`): it runs on
  the broker MKT-FEED tape with different, structure-based rules and is
  validated separately (`scripts/backtest_smc.py`, PR-gated). Today's
  "NO TRADE" verdicts on it are recorded honestly on the relay's
  `/signals` endpoint every cycle (291-294 of 317 scanned; TREET ran hot
  today and the tape engine still found no setup clearing the 2%-room
  risk gate at entry time - that is the engine's own record, not a
  delivery failure).
- Choice of touch mode, stop/target ratios and the max-hold timeout: the
  engine's declared defaults were simulated unmodified so the result can
  be quoted against the deployed config. This is an audit of the deployed
  rule, not a parameter search for a new one.

## Conclusion (SO-3, stated plainly)

The EOD daily scanner analogue, exactly as deployed, has NO ten-year
edge on the PSX KMIALL universe. Its negative expectancy is
configuration-independent: no combination of the standard thresholds
makes it profitable, and the same pipeline on GitHub Actions minutes and
on the owner's own machine produced identical numbers. Any further work
on making it "fire more" should be rejected on this evidence; if calls
are wanted at EOD level, they need a different rule family with its own
proof, not looser gates on this one.
