# KMI Sentinel - Accuracy Improvement Roadmap

The guiding rule: **every addition must earn its place through measured
results, not complexity.** Nothing below gets promoted to live trading
weight until the data says so.

---

## 0. Current Baseline (updated v0.11.2)

| Layer | Status |
|---|---|
| Universe | ~296 symbols (Shariah-filtered, ETF/REIT-excluded) |
| Live feeds | Market 5s polls, ToWatch (intraday), FIPI/LIPI institutional flow (per-session, all 9 investor classes + investor×sector matrix), news / announcements (post-close) |
| Scoring | 19-component rank composite + 16-component z-score master |
| Advanced math | Kalman trend (t-stat), Parkinson + Garman-Klass vol, cross-day volume baselines, correlation blocking |
| Gates | Conviction 0.55 (0.62 weak tape), evidence >= 5, breadth 40% normal / **35% hard floor**, green-tape-only longs, chase cap, index-vs-SMA regime, foreign-flow exodus (Rule 12), institutional war gate (Rule 12b), sector guard, multi-day extension cap, strong-horse exception, cap 3/day, daily loss breaker |
| Exits (v0.11) | **TP 2.0% floor / 3.0% preferred**, stop 1.5%, trail 1.0%→0.5%, 5-second stop checks, force-close at session end |
| Cost model | Full PSX fee schedule in `exit_frontier.py`: commission 0.15%/side (>20 PKR) or 0.03 PKR/share (<=20), SST 16% of commission, ~0.05% levies/side, 15% CGT - round trip 0.448% of value in the >20 PKR band |
| Cloud | GitHub Actions closes the books after every session (positions, baselines, outcomes, lessons) - `cloud-close.yml` |
| Console | Private local web console (`start_console.bat` → 127.0.0.1:8785, token-gated), starts/stops the bot, cadence selector |
| Tests | 468 passing |
| Book | 11 labeled trades, 4W/7L - all losses pre-date the v0.5.0 hard floors; replay shows the floors refuse every one of them |

**Dormant components and their activation clocks:**

| Component | Unlocks at |
|---|---|
| IC-calibrated weights (walk-forward sweep) | ~30 labeled trades (currently 11) |
| Regime-switched weight sets | After IC weights are measured |
| Model tier (logistic / GBT) | 60+ sessions - do not rush |

---

## 1. Risk Classes (read before touching anything)

| Class | Definition | Blast radius |
|---|---|---|
| **A - Additive** | New feature columns, new fetchers, new data files | Cannot change existing behavior; ignored if NaN |
| **B - Config** | Threshold/gate values in `config.json` | Reversible with one edit |
| **C - Core** | Replaces live logic (flat stop -> ATR stop; hand weights -> IC weights) | Requires shadow mode + explicit approval |

Every item below is tagged. **Class C items are never applied directly** -
they first run in shadow mode (computed, logged, not acted on) for at
least 5 sessions.

---

## 2. Tier 1 - Computable Today (no new data sources)

### T1.1 Running VWAP
- **What:** Session cumulative VWAP per symbol; score = price/VWAP - 1
- **Math:** `vwap = Σ(value) / Σ(volume)` over today's ticks; `vwap_ratio = price/vwap - 1`
- **Where:** `build_kmiall_features.py` → new `add_vwap_features()`; new master component `z_vwap_ratio` (~10% weight, taken from momentum_1m)
- **Data:** existing `value`/`volume` columns (cumulative daily) - free
- **Class:** A
- **Effort:** 2-3 hours
- **Tests:** VWAP equals first price at open; ratio > 0 when price > VWAP; session boundary reset
- **Earns its place by:** IC of z_vwap_ratio vs next-30min return, measured after 2 weeks
- **Meaning:** price holding above a rising VWAP = institutional buyers in control

### T1.2 Opening Range Breakout
- **What:** First 30-min high/low per symbol; score = distance above range high (0 below)
- **Math:** `range_high = max(high[t0..t0+30m])`; `orb_score = clip((price - range_high)/range_high, -1, +1)`
- **Where:** `build_kmiall_features.py` → `add_opening_range_features()`; master component `z_orb` (~5%)
- **Data:** existing per-snapshot high/low
- **Class:** A
- **Effort:** 2 hours
- **Known gap:** bot starts 09:45, market opens 09:32 - the range is built from 09:45+ data only. Acceptable (first 13 min is the most volatile/noisy anyway), but note in the report. Optional: start bot at 09:32 to capture the true open.
- **Tests:** range frozen after first 30 min; breakout score positive only above range high
- **Earns its place by:** breakout-then-continue rate vs. baseline

### T1.3 Gap Detection
- **What:** Morning gap per symbol = open/prior_close - 1
- **Math:** `prior_close = price / (1 + changePercent)` at first tick of day; `gap_pct = first_price/prior_close - 1`
- **Where:** `build_kmiall_features.py`; master component `z_gap` (small, ~3%); also feeds a *fade risk* flag
- **Class:** A
- **Effort:** 1-2 hours
- **Tests:** prior-close reconstruction matches known values; gap decays to 0 by close
- **Earns its place by:** gap-and-go vs gap-fade asymmetry in PSX (measured)

### T1.4 Garman-Klass Volatility
- **What:** More efficient range vol estimator than Parkinson (uses OHLC, not just HL)
- **Math:** `GK = sqrt(0.5·ln(H/L)² - (2·ln2-1)·ln(C/O)²)` per window; O = window's first price, C = last, H/L from per-snapshot high/low
- **Where:** `advanced_math.py` → `garman_klass_volatility()`; feature `gk_vol_score`; complements (does not replace) Parkinson
- **Class:** A
- **Effort:** 3-4 hours (window OHLC reconstruction is the fiddly part)
- **Tests:** GK ≤ Parkinson on same window (mathematical property); zero when flat
- **Earns its place by:** correlation with realized next-30min range vs. Parkinson's

### T1.5 Liquidity Floor + Amihud
- **What:** (a) Hard filter: skip symbols with day value < threshold; (b) Amihud illiquidity feature
- **Math:** filter: `value_today >= min_day_value` (default Rs. 20M, in `config.json`); feature: `amihud = |return| / (value/1e6)`
- **Where:** `decision_engine.py` → new filter step in `_filter_candidates`; `config.json` → `min_day_value`
- **Class:** B (the filter changes which candidates pass; threshold conservative to start)
- **Effort:** 1-2 hours
- **Tests:** thin names excluded; liquid names unaffected; configurable
- **Earns its place by:** reduction in unexitable-position losses (measured by slippage at force-close)

### T1.6 Circuit-Breaker (Price-Lock) Filter
- **What:** Never enter a stock locked at upper/lower circuit
- **Math (detection heuristic):** `change_pct >= 9.5` AND price == day high AND price unchanged over last N (12) ticks → locked-at-upper (mirror for lower)
- **Where:** `decision_engine.py` → new rule (Rule 8: no locked entries)
- **Class:** B
- **Effort:** 2-3 hours (heuristic tuning; false positives = missed trades, false negatives = worse)
- **Tests:** synthetic locked feed → filtered; normal strong mover → passes
- **Earns its place by:** zero entries on locked stocks (it's a correctness rule, not a signal)

### T1.7 Time-of-Day Weighting
- **What:** Session-phase multiplier on momentum components
- **Math:** phase = minutes-since-open; U-shaped credibility: `w(t) = 0.7 + 0.3·max(0, |t - 210|/210)` (full weight near open and close, 70% midday)
- **Where:** `build_kmiall_features.py` - applied to `z_momentum_1m`, `z_kalman_trend` at blend time
- **Class:** A (feature-scale change; conservative multiplier)
- **Effort:** 2 hours
- **Tests:** multiplier curve; no effect on other components
- **Earns its place by:** IC of momentum components by time bucket (needs 2 weeks)

**Tier 1 total: ~15 hours, all Class A/B, zero new dependencies.**
**Batch order: T1.5 (risk reduction) → T1.6 (correctness) → T1.1 (VWAP) → T1.2 → T1.3 → T1.7 → T1.4**

---

## 3. Tier 2 - New Crawlers (site pages not yet tapped)

### T2.1 Daily History Crawler → multi-day context
- **What:** `fetch_daily_history.py` → `data/daily_history.json` (per symbol: ~60 daily OHLCV rows from symbol-page chart data)
- **Unlocks (in dependency order):**
  - **T2.1a** 5d/20d returns → relative-strength component (Class A)
  - **T2.1b** Support/resistance proximity → `z_distance_from_20d_high` (Class A)
  - **T2.1c** **ATR-based stops** - replaces flat -2% stop with `entry - 1.5·ATR(14d)` (Class C: shadow-mode first, 5 sessions min)
  - **T2.1d** Relative strength vs KSE-100 (needs index history too) (Class A)
- **Effort:** crawler 4-6 hours + each unlock 2-4 hours
- **Recon needed:** verify what the symbol pages expose (chart JSON? embedded series?)
- **Earns its place by:** per-unlock IC; ATR stop by comparison of realized stop-distance vs. flat stop on same trades

### T2.2 Dividend Calendar
- **What:** `fetch_dividends.py` → `data/dividends.json`
- **Use:** Decision filter - no new entry within 2 trading days before a symbol's ex-div date (mechanical price drop ≠ signal)
- **Where:** `decision_engine.py` filter + post-close refresh in `live.py`
- **Class:** B
- **Effort:** 2-3 hours
- **Earns its place by:** zero ex-div entries (correctness rule)

### T2.3 Yields (T-bill rates)
- **What:** `fetch_yields.py` → `data/yields.json`
- **Use:** macro regime input - rate direction tilts bank/cement sector flow weights (e.g., falling rates → bank tailwind +)
- **Class:** A
- **Effort:** 2-3 hours crawl; the *use* is deliberately low-weight (~3%)
- **Honest note:** weakest signal of the whole roadmap on intraday timescales - include only if 2 weeks of data shows any edge

### T2.4 Fundamentals Crawl (one-off)
- **What:** `build_fundamentals.py` → `data/fundamentals.json` (P/E, ROE, div yield - same crawl pattern as company names)
- **Use:** quality tiebreaker, `z_quality` at 3-5% master weight - among two momentum equals, prefer the real company
- **Class:** A
- **Effort:** 4-5 hours (307 pages, ~5 min crawl) + join 1-2 hours
- **Earns its place by:** win-rate delta between top-quartile-quality signals vs. bottom-quartile (measured after 3-4 weeks)

---

## 4. Tier 3 - Calibration Phase (needs 20-30 labeled sessions)

*Prerequisite built NOW (Class A, this week):* `calibration/daily_outcomes.py`
- after each session close, append every signal + its triple-barrier
label (+2% target / -2% stop / time exit) to
`data/outcomes.jsonl`. **The labels already exist implicitly in
portfolio.json + decisions.jsonl - this just assembles them.** Without
this file, Tier 3 stays blocked; with it, everything below unlocks on
schedule.

### T3.1 Information Coefficient (IC) Analysis - the big one
- **What:** `calibration/ic_analysis.py` - per component, Spearman rank
  corr between its score at signal time and the realized triple-barrier
  outcome
- **Output:** `data/weights_measured.json` - measured weights file that
  overrides the hand-picked COMPONENTS/MASTER_COMPONENTS dicts
- **Application:** Class C. Shadow mode first: run 5 sessions computing
  decisions under measured weights, log both, compare, then switch on
  explicit approval
- **Effort:** 6-8 hours
- **Rolling:** recomputed weekly; components with |IC| < 0.02 get weight 0
- **This is the single largest accuracy jump in the roadmap**

### T3.2 Triple-Barrier Labeling
- **What:** the labeling scheme T3.1 consumes (which barrier hit first)
- **Effort:** included in the outcomes assembler above (2-3 hours)

### T3.3 Variance-Ratio / Hurst Regime per Stock
- **What:** VR(q) test on intraday returns → symbol is trending (VR>1) or mean-reverting (VR<1)
- **Use:** momentum components get full weight only on trending symbols; mean-reverters get a fade-capable treatment or exclusion
- **Class:** A as feature; B as filter
- **Effort:** 4-6 hours
- **Needs:** clean multi-session intraday history (have it after week 2)

### T3.4 Regime-Switching Weights
- **What:** 2-3 weight sets (calm-strong / choppy-weak / high-vol) keyed off breadth + GK vol; feature engine picks the active set per session
- **Class:** C - shadow mode
- **Depends on:** T3.1 (the weights themselves must be measured before they can be switched)
- **Effort:** 6-8 hours after T3.1

---

## 5. Tier 4 - Model-Based (needs 60+ sessions; do not rush)

### T4.1 Online Logistic Regression
- **What:** 16 features → P(win) per candidate; updates after every labeled trade
- **Use:** second-opinion gate - ENTER requires P(win) > calibrated threshold alongside existing gates
- **Class:** C - shadow mode 10+ sessions
- **Effort:** 8-10 hours (pure numpy; no new dependency needed)
- **Overfit guard:** 16 parameters vs. 60+ sessions of ~3 signals = ~180 labels - adequate, barely

### T4.2 Gradient-Boosted Trees + Purged CV
- **What:** only if T4.1 shows real signal
- **CV:** purged walk-forward with embargo - **never standard k-fold** (leaks future data, lies about accuracy)
- **New dependency:** scikit-learn (first new package since project start)
- **Class:** C
- **Effort:** 15+ hours
- **Do not start before Day 60.**

---

## 6. Sequencing Calendar - where we actually are (v0.11.2)

Tier 1 is **fully shipped** (liquidity floor, circuit breaker, VWAP,
opening range, gap, time-of-day, Garman-Klass). Tier 2: index history
and institutional flow are live; daily-history crawler, dividend
calendar and fundamentals crawl remain optional adds. The Tier 3
prerequisite (`outcomes.jsonl` labeling) is done and runs daily on
GitHub. The next scheduled milestone is the **walk-forward parameter
sweep at ~30 labeled trades**, tuned for win rate and expectancy
together against the real cost model. Tier 4 stays parked until Day 60+
as written below.

---

## 7. Verification Protocol (applies to every item)

1. **Tests first** - every item ships with unit tests; suite must stay green (468 and growing)
2. **Shadow rule for Class C** - computed and logged ≥ 5 sessions before it can act
3. **Earn-in metric** - each item above defines the number that justifies it; if the metric isn't met after 2 weeks, the component's weight goes to 0 (the architecture already renormalizes around dead weight)
4. **One batch per restart** - changes apply at next `start_live.bat`; never mid-session
5. **Rollback** - Class B via config edit; Class A components ignored if their data file is absent

---

## 8. Versioning

Every batch of changes is committed to git and pushed to the private
GitHub remote. Releases are tagged `vMAJOR.MINOR.PATCH`:

- **MAJOR** - a rule or architectural change that alters what the bot
  is (e.g., a new decision rule, the self-learning layer)
- **MINOR** - a new capability that does not change existing behavior
  by default (a new report, a new fetcher)
- **PATCH** - fixes and tuning with no behavioral redesign

Tags mark "the state of the bot that produced these outcomes" - the
version is part of the evidence when judging a change, which is the
whole point of paper trading. Current version: **v0.11.2** (v0.11.0/1
cost-correct exit policy: 2-3% targets against the full PSX fee
schedule; v0.10.0 institutional flow layer; v0.9.0 measured exit
policy; v0.8.0 5-second exit guard; v0.7.0 cloud bookkeeping).

---

## 9. What We Are NOT Doing (and why)

- No auto-trading / broker connection (explicitly out of scope)
- No standard k-fold CV anywhere (leaks future data)
- No deep learning (3 signals/day × 60 days = 180 labels; a neural net would memorize noise)
- No changes to the 3-entry cap or intraday-only discipline - those are structural, not tunable
- Alerts: Telegram push is the approved next add (owner request, 2026-09-13);
  the web console remains local-only by design
