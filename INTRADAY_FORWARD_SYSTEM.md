# Intraday Forward Validation System

Status date: 2026-10-08 (Karachi)

## Status

The repository now contains a chronological intraday paper scanner and an
automatic forward-evaluation gate. It does not claim a validated edge or
production eligibility. Genuine intraday history is currently too short to
evaluate this rule. The live signal path remains closed until the stored,
locked evidence gate passes.

The new research storage routes are part of `cloud/worker.js`. The deployed
Cloudflare Worker must be updated before observations and outcomes can be
stored in its KV namespace. Until that happens, scheduled capture continues
and the run artifacts disclose that persistent research storage is
unavailable. No signal is sent without a readable, eligible gate.

## Causal decision rule

The scanner reads only KMIALL and Shariah-compliant symbols in
`src/data/universe_kmiall.json`. It consumes genuine one-minute OHLC bars and
forms five-minute bars only from five consecutive minutes. A bar timestamp
means the close time of its completed five-minute interval. Any bar at or
after the scan time is excluded.

A scan needs at least 60 minutes of session observation and complete five
minute coverage for at least 80% of the universe. The broad-market proxy is
the cross-sectional median return plus the share of advancing symbols. It
requires median return of at least 0.10% and at least 55% advancers. This is
not the official KMIALL index.

A candidate must close above the high of the first 30-minute range, show at
least 0.25% relative strength over the universe median, remain no more than
1.00% above its session open, and remain within 0.50% of its current session
high. The highest relative-strength score wins only if it exceeds the runner
up by at least 0.10 percentage points. Otherwise the result is NO TRADE.
There is one paper winner at most per day. End-of-day research labels the
earliest passing candidate for that day.

The captured feed has no intraday volume, bid/ask, depth, or order flow.
Those inputs are not inferred from OHLC. Entry is the completed bar close as a
paper reference, not an executable price. The target is exactly entry times
1.02; the adverse reference is entry times 0.99. This scanner has not been
shown to have positive expectancy.

## Outcome and cost rules

Only bars after the decision timestamp are used. If target and stop are both
touched within one five-minute bar, the label is stop-first because ordering
cannot be recovered from OHLC. A stop gap fills at the bar open when that open
is below the stop. Otherwise the stop fills at the stop level. A target fills
at the exact +2.00% level. If neither is touched, the last completed intraday
bar is the close-out reference.

The evaluator charges 22.4 basis points per side, 10 basis points of slippage
per side, and 15% CGT on positive net returns. These are frozen model inputs,
not a guarantee of obtainable execution prices.

## Automatic evidence gate

The worker stores paper observations, one daily outcome, and the
machine-readable production gate. The first 180 captured trading sessions are
split once into 60 discovery, 60 validation, and 60 locked OOS sessions.
There is no strategy retuning or window rolling after the locked evaluation.
Minimum completed trades are 30 in discovery, 30 in validation, and 40 in
OOS. Each window must have positive net expectancy. OOS must also have a
positive lower 95% bootstrap bound, profit factor at least 1.10, and no more
than 60% of picks among the ten most selected symbols.

No candidate, incomplete capture, or unverifiable outcome does not count as a
trade. Insufficient samples, failed criteria, unavailable storage, and invalid
data all keep the live gate closed. A failure of the frozen OOS window locks
the strategy as failed rather than promoting or tuning it automatically.

## Cloud schedule and current evidence

The workflow captures at 10:45, 12:45, 14:45, and 16:45 PKT. It scans at the
first three times and labels the selected paper observation after the close.
The scheduled maximum is 1,380 Actions minutes for capture plus 460 minutes
for the existing daily signal jobs in a 23-weekday month, 1,840 total against
the documented 2,000-minute allowance.

The audited evidence at implementation time is one genuine intraday session
from 2026-10-06, around 32,639 one-minute bars across 298 symbols. This is not
enough for the 180-session gate. The five-year daily dataset and its roughly
27.5% positive-net result do not validate this intraday scanner. See
`RESEARCH_FINAL_AUDIT.md` for the exact daily rule, denominator, fill law,
biases, and limits.

No order-placement code, broker integration, leverage, short selling, or
futures were added.
