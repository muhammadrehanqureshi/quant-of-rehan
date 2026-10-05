"""
PSX KMIALL BOT
Decision engine - consumes feature rankings and enforces the six strategy rules.

This is the layer that sits between the feature engine (a research scoring
tool) and the portfolio tracker (position management). It decides WHEN to
act and WHICH symbol to act on, but does not execute orders itself.

The six strategy rules
----------------------
1. KMIALL universe only - already guaranteed by the feature engine, but
   enforced again here as a hard gate.
2. One winner per decision, not a basket - the engine picks the single
   best-ranked symbol, never a portfolio.
3. 1%-4% profit target - the engine suggests a target price at entry
   based on the current price. The portfolio tracker monitors exits.
4. No chasing a move that has already run - reject symbols whose
   same-day change exceeds a configurable threshold (default ±6%),
   or whose price position in the day range is above 0.85 (near the
   high, likely extended).
5. Stand aside when broad-market breadth is weak - when breadth_pct
   drops below a configurable threshold (default 35%), no new entries.
6. Maximum 3-trading-day holding period - the portfolio tracker enforces
   this on exit. The decision engine respects it by not re-entering a
   symbol that is already held.

10. Trend is your friend - a candidate must be trading above the
   session VWAP: rising AND bought, not rising on fumes. The bot buys
   strength, not hope; a symbol falling or drifting below VWAP is
   passed over regardless of score.

Market-regime layer ("be with the market, not against it") - the
per-stock filters above cannot see the tape. Rules 11-15 use a
MarketContext (src/market_regime.py) built from market-level data;
every gate passes on unknown evidence:

11. Index regime - no longs while the KSE-100 trades below its
   20-session average; the whole market is the trend that matters.
11b. Breadth collapse - stand aside when session breadth has fallen
   10+ points from its intraday high (open-strength unwinding).
12. Foreign-flow regime - stand aside after an emphatic multi-session
   foreign net-sell streak (the documented PSX correction driver).
13. Morning window - no entries in the first 30 minutes after the
   open (the noisiest, most gap-fade-prone stretch of the PSX day).
14. Sector guard / cap - no entries in a sector down >2% today; one
   position per sector max (the same trade twice is not diversity).
15. Multi-day extension - no chasing a stock already up >15% over
   its last 5 sessions even when today's change alone looks tame.

The self-learning layer (src/lessons.py) adjusts behaviour within
these rules: it can blacklist persistently losing symbols, rescale
the ranking, and tighten the conviction gate after a losing stretch.
It can never loosen a rule.

Design
------
The engine is stateless with respect to positions - it does not track what
the portfolio owns. The portfolio tracker tells it what is held, and the
engine filters its candidate list accordingly. This keeps the two concerns
separate and testable.

Usage
-----
    from psx_core import paths
    paths.bootstrap_import_path()

    from psx_core.features import load_features
    from decision_engine import DecisionEngine, DecisionConfig

    df = load_features(path)
    engine = DecisionEngine(DecisionConfig())
    decision = engine.evaluate(df, held_symbols={"EFERT"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import math

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DecisionConfig:
    """
    Tunable thresholds for the six strategy rules.

    Defaults are conservative. They must be validated on real multi-day
    data before any live deployment.
    """

    # Rule 4: no chasing a move that has already run.
    max_same_day_change_pct: float = 6.0

    # Hard floor (v0.5.0) - the unwaivable tape-quality minimums. Every
    # other gate has a documented override (recovery mode, strong
    # horse); these do not, because every labeled loss in the ledger
    # entered in a regime these lines exclude (sub-35% breadth, red on
    # the day, or a bounce-chase far off the low). They are measured
    # from the bot's own outcomes, not asserted from theory.
    hard_min_breadth_pct: float = 35.0
    require_positive_day_change: bool = True
    max_entry_off_low_pct: float = 3.0
    recovery_max_entry_off_low_pct: float = 6.0
    max_price_position: float = 0.85

    # Rule 8: liquidity floor (T1.5) - a signal in a stock that has
    # traded less than this much value today cannot be exited
    # reliably intraday. Rs. 5M default for PSX; some PSX stocks
    # hit upper circuit with very low volume (e.g. 10,000 shares)
    # and are still valid strong-trend candidates. 0 disables.
    min_day_value: float = 5_000_000.0

    # Rule 22 - anti-predictive score ceiling (v0.18.0). The engine's
    # own composite score in its top tail predicted LOSERS: forward
    # win rate 11.6% above 0.7 vs 29.5% below, session-consistent.
    score_ceiling_veto: bool = False  # enabled in config.json (live policy)
    score_ceiling: float = 0.70

    # Rule 24 - the chase penalty (v2.1.0, continuous demotion). The
    # morning premium above the prior close is the most
    # anti-predictive entry feature this book has measured: 437 of
    # 450 panel candidates were already up >= +3% when flagged, won
    # 14% of forwards at -1.25% net, while the off-low-3-5%
    # pullback cohort won 44%. Survivors of the hard cap are DEMOTED
    # (rank and conviction) rather than banned - recovery days need
    # the cap relaxed, and the penalty scales with evidence, not a
    # binary gate. 0.08 per 1% beyond +1% on the day, capped 0.25.
    chase_penalty_per_pct: float = 0.08
    chase_penalty_cap: float = 0.25

    # Rule 25 - the chase hard veto (v2.2.0, 2026-09-21). The 450-panel
    # forward simulation under the live exit policy put the blow-off
    # cohort (+8% or more over the prior close at signal time) at a
    # 6.9% win rate and -2.18% net per trade - nowhere near the 61.6%
    # breakeven the TP2/SL1 book needs - and the 12-config exit grid
    # could not make that band positive under any TP/SL pair. Rule 24
    # demotes these candidates; the data says demotion is not enough.
    # Banned outright. Sits below the 9.5% circuit-breaker line so a
    # blow-off dies before the lock detector ever sees it. A candidate
    # with no day-change passes (the gate never invents a veto).
    # Default-on: the evidence is session-consistent, the live config
    # mirrors it, and the kill-switch stays available for the refit loop.
    chase_hard_veto_enabled: bool = True
    chase_veto_max_change_pct: float = 8.0

    # Rule 26 - the low-conviction green-open ban (v2.4.0). Grind-4
    # evidence (175 sessions, 3,799 trades in the family): mild green
    # days (0-2%) without lock-class momentum win 13.4% at -0.79% net,
    # negative in every month of 2026. Candidates inside the band are
    # refused UNLESS their master score clears dead_zone_max_score -
    # a genuinely strong tape can occasionally earn the exception, and
    # the escape hatch keeps the refit loop's knobs meaningful.
    dead_zone_veto_enabled: bool = True
    dead_zone_max_change_pct: float = 2.0
    dead_zone_max_score: float = 0.70

    # Rule 9: circuit breaker (T1.6) - never enter a stock locked at
    # its daily price band. Detection: change >= 9.5% AND price pinned
    # at the day high AND price frozen over the recent window.
    circuit_breaker_change_pct: float = 9.5

    # Rule 5: stand aside when breadth is weak.
    # 2026-09-10 evidence: every stop-out to date entered at breadth
    # <= 32.7% (the old 30 floor let all of them through), both wins at
    # >= 45.6%. 40 is the evidence-backed floor; revisit at 20+ labels.
    min_breadth_pct: float = 40.0

    # Rule 5b - money-tape recovery override (2026-09-11 lesson).
    # Equal-weight breadth answers "is the average stock up?" - a
    # cap-weighted V-reversal (KSE-100 -2200 -> +1600 on the oil/bank
    # heavyweights) shows 42% breadth at the very top because the
    # average stock never joined. The money-weighted tape and its
    # 30-minute slope do see it: vw-change crossed positive with a
    # +3.5%/30min slope at 14:40. When both confirm, the breadth floor
    # does not stand aside from a rising market: the tape's money is
    # the more honest witness. Missing columns = old behaviour.
    money_tape_recovery_enabled: bool = True
    money_tape_min_vw_change_pct: float = 0.0
    money_tape_min_slope_30m: float = 1.0

    # Rule 5c - recovery mode (2026-09-11 post-mortem). A V-reversal
    # afternoon breaks three gates that were tuned on grinding days:
    #   * the +4% same-day cap rejects the stocks leading the recovery
    #     (PRL +6.5% on Rs 4.5bn traded - the tape's leader);
    #   * sector money-flow compares against an EWMA still anchored to
    #     the morning's crash weights, so leading sectors read low;
    #   * Rule 16 anchors "confirmation" to the DAY high - but on a V-day
    #     the high is the morning-spike top, hours stale; the recovery
    #     itself is pressing the RECENT high (off the low).
    # Recovery detector (honest, measured): money-weighted change >= 0
    # AND the median stock is >= recovery_min_off_low_pct off its session
    # low (normal afternoons: 0.2-1.1%; 2026-09-11 recovery: 3.9-4.7%)
    # OR a >= +3%/30min money-slope for the early leg. All-or-nothing:
    # one missing column = no recovery mode. Normal days are untouched -
    # the detector cannot fire when the board is not bouncing.
    recovery_mode_enabled: bool = True
    recovery_min_off_low_pct: float = 3.0

    # Third recovery trigger (v0.14.2, 2026-09-15): BROAD RALLY breadth.
    # The off-low and slope triggers are V-reversal detectors - they
    # need the board to have been down first. A gap-up rally (the most
    # common strong-day shape on the PSX) opens up and grinds higher:
    # the whole board sits ~1% off its lows all day and the 30-min slope
    # never spikes, so recovery never armed and the tight caps refused
    # every real leader (2026-09-15 +1700 day, breadth 76-79%, zero
    # entries). 70%+ of the board green with a non-negative money tape
    # IS the rally; it needs no bounce evidence because there was no
    # dip to bounce from. Rule 11b (breadth collapse) still blocks a
    # rally that is fading, and the hard floor is untouched.
    recovery_breadth_arm_pct: float = 65.0
    recovery_slope_30m: float = 3.0
    recovery_max_day_change_pct: float = 8.0
    recovery_recent_high_minutes: float = 45.0
    recovery_rise_lookback_minutes: float = 15.0

    # Strong-horse exception to Rules 5 and 11. A blanket stand-aside on
    # weak-tape days also forfeits the 2-10% runners bad sessions still
    # produce (2026-09-10: ~70% of the board red, several names still
    # closed +2..10%). When the market tape is weak, the engine may still
    # enter a STRONG HORSE - a stock beating the market's median change
    # by a wide margin, trending hard, above VWAP, clearing a higher
    # conviction bar, and allowed to be further extended on the day
    # (circuit/frozen checks still apply). Everything else stands aside
    # exactly as before.
    strong_horse_enabled: bool = True
    strong_horse_min_outperformance_pct: float = 3.0
    # 2026-09-14: 0.70 was calibrated on 9 labels and blocked the day's
    # best candidate (ATRL 0.691, top of the board, +5.3%) by 0.009 while
    # the recovery override had already disarmed Rule 11 itself. 0.65
    # admits such tape-leaders on downtrend-file days; every labeled loss
    # entered below the 35% hard floor, which is untouched.
    strong_horse_min_score: float = 0.62
    strong_horse_max_same_day_change_pct: float = 9.0

    # Rule 27: penny-stock floor (v4.2.1, 2026-10-01). Sub-Rs-10
    # names (KEL 6-7) produced fake calls the owner cannot trust:
    # thin tapes, wide effective spreads, tick-level noise that
    # flips intraday signals. No entry below the floor - missing
    # price fails closed. Raising or lowering this is a config
    # change, never a code change.
    min_entry_price: float = 10.0

    # Rule 11 - index regime ("be with the market"). When the KSE-100's
    # last close sits below its N-session average, the market itself is
    # in a downtrend and intraday longs are fighting the tape; the
    # engine stands aside regardless of how good an individual stock
    # looks. Verified against the 2026-08/09 correction: the index
    # fell below its 20-session average on the way down and the bot's
    # four stop-outs all happened while it was there. Unknown (no
    # history) = pass: the gate never invents evidence.
    index_regime_enabled: bool = True
    index_sma_window: int = 20
    # v2.1.0 Rule 11c - the live session tape (owner's standing law,
    # 2026-09-20: "if the index is having a green day then most of the
    # stocks will be having a green day"). When the KSE-100's LIVE
    # day-change is at or below this floor, the cap-weighted market is
    # being sold and no intraday long is taken. An unknown or stale
    # quote degrades the gate to pass - it never manufactures a veto
    # from absent evidence.
    index_tape_enabled: bool = True
    index_tape_floor_pct: float = -0.5

    # Rule 11 data-quality veto. A stale regime input is not "the market
    # is fine" - it is "we cannot see the market". When the index gate is
    # on and its history does not reach the last completed session, all
    # entries stop (loudly) until the data heals, instead of the gate
    # passing silently on absent evidence.
    regime_data_veto_enabled: bool = True

    # Rule 11b - breadth collapse. The floor above is a level; this is
    # the shape. When session breadth has fallen this far from its
    # intraday high, sellers are taking control in real time and the
    # morning's "strength" is unwinding (2026-09-10: 31.6% -> 17% while
    # the morning's entries died). Unknown = pass.
    max_breadth_drop_pct: float = 10.0

    # Rule 12 - foreign-flow regime. DEMOTED TO ADVISORY (v0.14.1,
    # 2026-09-15): as a hard veto it blocked every cycle of the +1700
    # point rally that morning on a "3-session selling streak" whose
    # tail was -292k / -6.4M / -651k - and every rally day in the
    # stored history (Sep 11 V-reversal, Sep 14 refinery, Sep 15) was a
    # foreign-net-selling day. Three-day-old flow data must never
    # override what the live tape is doing. The streak still rides in
    # every decision's regime metadata; the tape decides.
    foreign_flow_regime_enabled: bool = True
    foreign_flow_streak_days: int = 3
    foreign_flow_min_net_usd: float = -5_000_000.0

    # Rule 12b - institutional positioning (v0.10.0). NCCPL FIPI/LIPI
    # investor-type flows, per session. Two read-outs ride along in
    # every decision's regime metadata (never score inputs):
    #   inst_smart_retail_war -- institutions net selling while retail
    #     (Individuals) net buys at least divergence_ratio times as
    #     hard: smart money distributing to the crowd. A hard block
    #     when armed; DORMANT until per-session investor history
    #     accumulates enough sessions to measure a baseline.
    #   inst_retail_fomo      -- retail net buying far above its own
    #     recent norm while the tape is weak: late-stage signature.
    #     Score-blunting only (meta note), never a crash signal on its
    #     own - Sep 10's evidence shows investor mix alone does not
    #     decide the day.
    institutional_flow_enabled: bool = True
    institutional_war_divergence: float = 2.0
    institutional_fomo_ratio: float = 1.35
    # v2.5.2: the war signature needs REAL size. Sep 23 vetoed every
    # cycle of the session on a -2.2M inst / +0.3M retail divergence -
    # rounding error on PSX volume, and exactly the
    # lagging-flow-kills-a-rally misfire v0.14.1 documented. The
    # institution side must bring $10M of actual distribution; retail
    # must show $1M of genuine participation.
    institutional_war_min_side_usd: float = 10_000_000.0
    institutional_war_min_retail_usd: float = 1_000_000.0

    # Rule 13b - the lunch doldrums ban (v2.1.0). The 450-panel mine
    # (every stored decide-step candidate, forward paths, real cost
    # stack) shows 12:30-14:50 PKT is the graveyard of this tape:
    # entries there won 5-10% of the time vs 17-20% in the morning and
    # late legs. The lunch drift has no institutional foot to stand on
    # - an entry here is a bet on noise. Times are PKT minutes-of-day;
    # 0/0 disables the window.
    no_entry_window_start_min: float = 750.0  # 12:30 PKT
    no_entry_window_end_min: float = 890.0    # 14:50 PKT

    # Rule 13 - the opening sniper doctrine (v0.21.0, owner's spec).
    # The PSX morning has a shape: the 09:32 open (09:17 Friday) is
    # auction chaos, the market hands back a pullback around minute
    # 15-20, and the strong names resume. Stand aside ONLY for the raw
    # chaos (first opening_hold_minutes), hunt the pullback inside the
    # sniper window (up to sniper_window_end_minutes), normal rulebook
    # after. The old flat 30-minute ban made the bot sleep through the
    # exact window the owner described; the ledger says the danger was
    # the auction, not the pullback (every ledger loss entered after
    # minute 35). The day's FIRST leg only: a post-lunch re-open
    # (Friday 14:32) is not a fresh open (2026-09-11 lesson).
    # opening_hold_minutes=0 disables.
    opening_hold_minutes: float = 15.0
    sniper_window_end_minutes: float = 35.0

    # Rule 14 - sector guard. Two ways a healthy-looking stock is
    # actually fighting the tape: its whole sector is being dumped
    # (refinery -3.5% on 2026-09-10 while ATRL "trended up"), and the
    # book already owns the move. A candidate whose sector's average
    # same-day change is below this threshold is rejected; a sector
    # already represented by an open position cannot add a second.
    # Missing sector data = pass.
    sector_guard_enabled: bool = True
    sector_guard_max_drop_pct: float = 2.0
    max_positions_per_sector: int = 1

    # Rule 15 - multi-day extension (no chasing across days). Rule 4
    # only saw today's move, so a stock up ~20% over two sessions
    # passed cleanly at the open on day three (ECOP, 2026-09-10) and
    # stopped out by 11:00. A candidate up more than this percentage
    # over the last k daily closes (k<=5, scaled: threshold*k/5,
    # k>=3) is rejected. Symbols without 3+ stored closes pass -
    # missing data never blocks.
    max_multi_day_gain_pct: float = 15.0

    # Rule 3: profit target range (applied at portfolio level).
    # v0.11.0: floor raised to 2.0% - below that, Mr. Rehan's real
    # costs (0.15% fee per side + 15% profit tax) eat the edge.
    # OWNER'S UNIVERSAL LAW (2026-09-21, standing order): the take
    # profit is 2.0% and the stop is -1.0% on BOTH bots, every entry,
    # forever. The 3% preferred target is retired - the owner's law,
    # not a parameter to be tuned away by any refit loop.
    profit_target_low: float = 2.0   # universal law: 2% TP
    profit_target_high: float = 2.0  # universal law: 2% TP (no step-up)
    # v0.20.2 time-aware TP (owner doctrine, 2026-09-19 postmortem):
    # an entry in the morning has hours of tape to reach the preferred
    # 3% target; an entry this many minutes into the session gets the
    # 2% floor instead - late entries chasing the close rarely clear a
    # long hike, and a reachable target is the one that gets hit.
    # 0 disables the step-down (always profit_target_high).
    tp_stepdown_minutes: float = 150.0

    # Rule 6: maximum holding period in trading days (intraday = 1 day).
    max_holding_days: int = 1

    # Minimum composite score to consider (filters noise).
    min_score: float = 0.0

    # Conviction gate - the anti-forcing rule. An ENTER requires the
    # candidate's preferred score (master z-score when available, else
    # the percentile composite) to clear this bar. The scores live in
    # (0, 1) with 0.5 as neutral: 0.55 means "meaningfully better than
    # the average stock right now". With this gate, an empty or choppy
    # market produces STAND_ASIDE - the bot never hands out the best
    # available symbol just because it is the best available. 0, 1, 2
    # or 3 signals per day are all acceptable outcomes.
    # The self-learning layer (src/lessons.py) may raise this bar
    # temporarily after a losing stretch; see
    # DecisionEngine.effective_min_master_score.
    min_master_score: float = 0.55

    # Rule 10 - trend filter ("the trend is your friend"). A candidate
    # must be trading above the session VWAP - rising AND bought, not
    # rising on fumes. (v3.1.1: the Kalman trend floor and the Bollinger
    # %B stretch veto are removed from the rulebook by owner's order.)
    # A missing column is a pass: the filter never invents evidence,
    # it only refuses when the evidence says no.
    trend_filter_enabled: bool = True
    require_above_vwap: bool = True

    # Minimum number of distinct evidence components behind a candidate
    # before an ENTER is allowed. The master blend renormalises over
    # present components, so a single lucky column could otherwise
    # carry a symbol over the gate. This counts the non-NaN master
    # components (z_* columns) on the candidate's row.
    min_evidence_components: int = 5

    # Minimum weight coverage for a score to be trusted. Event-feed
    # components (news/announcements) are structurally sparse -
    # only ~5% of symbols carry a signal on a given day - so a healthy
    # row built from the dense components alone reaches ~0.68 coverage
    # after renormalisation. The 0.35 gate rejects genuinely thin rows
    # (early-session, suspended, data gaps) without punishing the
    # majority of solid unsignalled candidates.
    min_weight_coverage: float = 0.35

    # How many of the top candidates to inspect (we pick 1).
    candidate_pool_size: int = 5

    # (v3.2.0: max_held_correlation retired with the correlation gate.)

    # The z-score master score (advanced math layer) is preferred over
    # the percentile composite when present on a candidate.
    prefer_master_score: bool = True

    # Rule 16 - confirmation ("read, don't predict"). A candidate may
    # only enter when its price is pressing against the session high
    # (within this fraction of a percent of it) with positive 1-minute
    # momentum: buyers are present at THIS poll. The 2026-09-10 losers
    # passed Kalman/VWAP on stale evidence while fading off their
    # highs. Missing high/price columns or a flat session = no entry.
    confirmation_enabled: bool = True
    confirmation_at_high_pct: float = 1.5

    # How many minutes back a session-high print stays "fresh" for
    # Rule 16. A high made within this window means the move is still
    # developing; an hour-old high means the stock is digesting or
    # fading regardless of how strong its morning was.
    confirmation_fresh_minutes: float = 20.0

    # --- Classical technical-indicator vetoes (v0.17.0) -----------------
    # Each targets a specific losing cluster measured in the net ledger
    # (43 trades, 2.7% gross win rate after the honest-cost re-score).
    # Missing indicator columns = pass: the engine never invents
    # evidence, it only refuses when the evidence says no.

    # Rule 18 - overbought veto. The ledger's worst cluster is the
    # blow-off chase: entries after an extended run that mean-revert
    # through the stop (top-score "rockets" won 10% of the time in
    # the 450-candidate mining). RSI >= 80 is statistical exhaustion,
    # not strength - a long book does not buy it.
    max_entry_rsi: float = 80.0

    # Rule 19/20 - RETIRED v3.1.1/v3.2.0 by owner's order: the
    # Bollinger %B stretch veto and the volume/price divergence veto
    # are removed from the rulebook (not on the whitelist).

    # Rule 11 recovery override - the index history file is
    # end-of-day; it cannot see today. When the live tape shows a
    # broad-based recovery (breadth at/above this level, no collapse),
    # the EOD "downtrend" verdict is stale and the normal gates
    # (breadth floor, trend filter, confirmation) apply instead of
    # the strong-horse exception. 55% = clearly more advancers than
    # decliners, above the 40% normal-day floor.
    recovery_breadth_pct: float = 55.0

    # Rule 17 - follow the money (PSX-native). sector_money_flow_pct
    # is the sector's LIVE share of the market's traded value vs its
    # typical share: > 1 means rupees are concentrating into this
    # sector right now. A candidate from a sector below
    # min_sector_money_flow is being avoided by the market - the
    # tape's own money says no. 0 disables (missing column = pass,
    # the filter never invents evidence).
    min_sector_money_flow: float = 0.70

    # Rule 16b - buyer presence at the moment of entry. The live
    # order book must not be ask-stacked: bid_volume >= this fraction
    # of ask_volume. A stock "trending" while sellers queue up on the
    # ask side is distribution, not demand - the 2026-09-10 pattern.
    # Missing book columns = pass (never invents evidence).
    min_bid_ask_balance: float = 0.50


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    """One decision output: either ENTER a symbol or STAND_ASIDE."""

    action: str  # "ENTER" | "STAND_ASIDE"
    symbol: str | None = None
    score: float | None = None
    price: float | None = None
    profit_target_price: float | None = None
    profit_target_pct: float | None = None
    quantity: int | None = None
    capital_alloc: float | None = None
    reason: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "score": self.score,
            "price": self.price,
            "profit_target_price": self.profit_target_price,
            "profit_target_pct": self.profit_target_pct,
            "quantity": self.quantity,
            "capital_alloc": self.capital_alloc,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------

class DecisionEngine:
    """
    Stateless decision engine: evaluate a feature frame and return one
    Decision.

    Parameters
    ----------
    config : DecisionConfig
        Tunable thresholds.
    """

    def __init__(
        self,
        config: DecisionConfig | None = None,
        capital: float = 1_000_000,
        lessons: dict | None = None,
    ) -> None:
        self.config = config or DecisionConfig()
        self.capital = capital
        # Self-learning overlay (src/lessons.py). The engine applies
        # whatever lessons the caller loaded; it never reads the
        # lessons file itself, so a decision stays a pure function of
        # its inputs and remains trivially testable.
        lessons = lessons or {}
        self.blacklisted: set[str] = set(lessons.get("blacklisted") or ())
        # Rule 26 escape hatch (v2.5.0): symbols with PROVEN long-run
        # lock continuation (grind-6 per-symbol table: win >= 70% on
        # n >= 8) pass the dead zone below the normal ceiling.
        self.lock_memory_symbols: set[str] = set(
            lessons.get("lock_memory_symbols") or ()
        )
        # v2.5.1: the mirror image - symbols whose lock continuations
        # chronically fail (grind-6: win < 50% on n >= 3, negative net).
        # Banned from the dead-zone escape hatch in both directions:
        # never exempted by the strong-record list, and additionally
        # vetoed inside the momentum band entirely (Rule 26b).
        self.lock_banned_symbols: set[str] = set(
            lessons.get("lock_banned_symbols") or ()
        )
        self.score_scale = lessons.get("score_scale")
        self.min_master_score_adjustment = float(
            lessons.get("min_master_score_adjustment") or 0.0
        )
        # v2.6.0 - the daily market-learning overlay (src/
        # market_learner.py). Symbols the rolling lessons confirm DEAD
        # (>= 3 straight sessions flat AND illiquid) are off the menu:
        # a dead tape has no fuel for an intraday move. Confirmed
        # trenders are context, surfaced in metadata, never a free
        # pass - the gates still decide.
        self.market_dead_symbols: set[str] = set(
            lessons.get("market_dead_symbols") or ()
        )
        self.market_trend_symbols: set[str] = set(
            lessons.get("market_trend_symbols") or ()
        )
        # Latest decision's institutional regime read (Rule 12b);
        # surfaced by the console/monitoring without re-parsing JSON.
        self._inst_regime_meta: dict | None = None
        # v0.19.0 corporate-actions map (book closures / ex-dates /
        # fresh results). Injected by the caller from
        # data/corporate_actions.json; None = layer inert (missing
        # data must degrade to today's behavior, never crash a pass).
        self.corporate_actions: dict | None = None

    @property
    def effective_min_master_score(self) -> float:
        """Conviction gate after any self-learning adjustment."""
        return self.config.min_master_score + self.min_master_score_adjustment

    def foreign_flow_advisory(self, context: Any | None) -> dict | None:
        """Rule 12 as advisory (v0.14.1): the lagging foreign-flow read,
        for display and the regime metadata - never a veto. Returns None
        when there is no read (context missing or history absent)."""
        if context is None or not self.config.foreign_flow_regime_enabled:
            return None
        streak = getattr(context, "foreign_flow_streak", None)
        if streak is None:
            return None
        return {
            "foreign_flow_streak": streak,
            "foreign_flow_sum_usd": getattr(
                context, "foreign_flow_sum_usd", None
            ),
            "foreign_flow_blocked": bool(
                getattr(context, "foreign_flow_blocked", False)
            ),
            "advisory": True,
        }

    def evaluate(
        self,
        df: pd.DataFrame,
        held_symbols: set[str] | None = None,
        current_date: str | None = None,
        context: Any | None = None,
    ) -> Decision:
        """
        Pick the best actionable symbol from the latest timestamp, or
        stand aside.

        Parameters
        ----------
        df : DataFrame
            Feature-enriched dataset (output of build_kmiall_features).
        held_symbols : set of str
            Symbols currently held in the portfolio. These are excluded
            from the candidate pool (rule 6: no re-entry while holding).
        current_date : str
            The trading date being evaluated (YYYY-MM-DD). Used to filter
            rows.
        context : MarketContext-like, optional
            Market-level evidence (src/market_regime.py): index trend,
            foreign-flow streak, per-symbol daily closes. None = the
            regime gates (11-15) run on unknown evidence and pass.

        Returns
        -------
        Decision
        """
        held_symbols = held_symbols or set()
        now = datetime.now(timezone.utc).isoformat()

        # Weak-tape verdict (Rule 5 / Rule 11). When strong-horse mode is
        # on, a weak tape defers instead of blocking: the cycle may still
        # enter one exceptional stock, and everything about the candidate
        # pool tightens accordingly (see _filter_candidates and the
        # conviction gate below). Rule 11b still blocks outright - a live
        # breadth collapse is happening NOW. Rule 12 (foreign flow) is
        # advisory only since v0.14.1: lagging flow data must not veto a
        # live rally (it blocked the entire 2026-09-15 +1700 morning).
        strong_horse: dict[str, Any] | None = None

        # --- Slice to the latest timestamp -----------------------------------
        latest_ts = df["timestamp"].max()
        latest = df[df["timestamp"] == latest_ts].copy()

        if latest.empty:
            return Decision(
                action="STAND_ASIDE",
                reason="No data at latest timestamp",
                timestamp=now,
            )

        # --- Rule 11 data-quality veto: refuse to trade blind ----------------
        # Runs before every opinion gate. A regime input the gate is
        # configured to rely on must at least exist and be current; if it
        # is not, standing aside is the only honest decision - this is
        # the failure that let the 2026-09-10 morning entries through.
        if (
            context is not None
            and self.config.index_regime_enabled
            and self.config.regime_data_veto_enabled
            and getattr(context, "index_history_stale", False)
        ):
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Regime data stale: KSE-100 history newest session "
                    f"{getattr(context, 'index_history_newest', None) or 'none'}, "
                    f"expected {getattr(context, 'index_history_expected', None) or 'unknown'} "
                    "- refusing to trade on blind regime gates until the data heals"
                ),
                timestamp=now,
                metadata={
                    "gate": "regime_data_veto",
                    "index_history_newest": getattr(
                        context, "index_history_newest", None
                    ),
                    "index_history_expected": getattr(
                        context, "index_history_expected", None
                    ),
                },
            )

        # --- Rule 5: market breadth gate ------------------------------------
        breadth_pct = latest["breadth_pct"].iloc[0] if "breadth_pct" in latest.columns else None
        money_tape_recovery = False
        vw_ok = False
        slope = None
        if self.config.money_tape_recovery_enabled:
            vw = (
                latest["market_vw_change_pct"].iloc[0]
                if "market_vw_change_pct" in latest.columns else None
            )
            slope = (
                latest["market_vw_slope_30m"].iloc[0]
                if "market_vw_slope_30m" in latest.columns else None
            )
            vw_ok = (
                vw is not None and pd.notna(vw)
                and float(vw) >= self.config.money_tape_min_vw_change_pct
            )
            money_tape_recovery = bool(
                vw_ok
                and slope is not None and pd.notna(slope)
                and float(slope) >= self.config.money_tape_min_slope_30m
            )

        # Recovery mode (Rule 5c): the shape-of-the-market detector that
        # equal-weight breadth cannot see. On the 2026-09-11 V-reversal
        # the median stock sat 3.9-4.7% off its session low at 14:40+
        # while breadth read 42-46%; normal afternoons read 0.2-1.1%.
        # Two independent triggers, either arms recovery while the
        # money-tape itself is non-negative:
        #   * off-low: the board is broadly bouncing (fires at the leg
        #     open - the 30-min slope CANNOT exist then, the lunch gap
        #     voids it; requiring it delayed Friday's unlock to 15:15,
        #     after the strongest leg was over);
        #   * slope: the money is slamming back in (+3%/30min).
        recovery_mode = False
        if self.config.recovery_mode_enabled and vw_ok:
            off_low = (
                latest["market_off_low_pct"].iloc[0]
                if "market_off_low_pct" in latest.columns else None
            )
            off_low_ok = (
                off_low is not None
                and pd.notna(off_low)
                and float(off_low) >= self.config.recovery_min_off_low_pct
            )
            slope_ok = (
                slope is not None
                and pd.notna(slope)
                and float(slope) >= self.config.recovery_slope_30m
            )
            breadth_arm_ok = (
                breadth_pct is not None
                and pd.notna(breadth_pct)
                and float(breadth_pct) >= self.config.recovery_breadth_arm_pct
            )
            recovery_mode = bool(
                off_low_ok or slope_ok or breadth_arm_ok
            )
        # --- Hard floor (v0.5.0): the unwaivable tape-quality gate ----------
        # Runs BEFORE every override. Recovery mode and the strong-horse
        # exception were built to read past a weak AVERAGE - they were
        # never meant to license trading a DEAD tape. Every labeled loss
        # in the ledger entered below 35% breadth (Sep 10: three entries
        # at 30-32%, three losses), so this line admits no exception.
        if breadth_pct is not None and pd.notna(breadth_pct):
            if breadth_pct < self.config.hard_min_breadth_pct:
                strong_horse = None  # no exception outranks the floor
                recovery_mode = False
                money_tape_recovery = False
                return Decision(
                    action="STAND_ASIDE",
                    reason=(
                        f"Hard floor: market breadth {breadth_pct:.1f}% is "
                        f"below the {self.config.hard_min_breadth_pct:.0f}% "
                        f"minimum - no long will be taken here, no "
                        f"exceptions (all ledger losses entered below it)"
                    ),
                    timestamp=now,
                    metadata={
                        "breadth_pct": float(breadth_pct),
                        "gate": "hard_min_breadth_pct",
                    },
                )
        if breadth_pct is not None and pd.notna(breadth_pct):
            if (
                breadth_pct < self.config.min_breadth_pct
                and not money_tape_recovery
                and not recovery_mode
            ):
                reason = (
                    f"Rule 5: broad-market breadth is weak "
                    f"({breadth_pct:.1f}% < {self.config.min_breadth_pct:.0f}%)"
                )
                if self.config.strong_horse_enabled:
                    strong_horse = {
                        "gate": "Rule 5",
                        "reason": reason,
                        "breadth_pct": float(breadth_pct),
                    }
                else:
                    return Decision(
                        action="STAND_ASIDE",
                        reason=reason,
                        timestamp=now,
                        metadata={"breadth_pct": float(breadth_pct)},
                    )


        # --- Rule 11: index regime - be with the market ----------------------
        # The KSE-100 below its own average means the market as a whole
        # is being sold; an intraday long is a bet against every seller
        # in the building. Verified on the Aug-Sep 2026 correction: the
        # bot's stop-outs all happened below the line, and standing
        # aside there is the whole point of the rule.
        #
        # Recovery override: the index file is END-OF-DAY - it cannot
        # see today. When the live tape says the market is
        # broad-based rising (breadth at/above the recovery
        # threshold and no collapse), the EOD downtrend verdict is
        # stale by definition and the tape wins (2026-09-11: a
        # -2,200 → +600 reversal day was refused all afternoon
        # because the gate kept reading yesterday's close).
        if context is not None and self.config.index_regime_enabled:
            below = getattr(context, "index_below_sma", None)
            if below is True:
                live_breadth = (
                    float(breadth_pct)
                    if breadth_pct is not None and pd.notna(breadth_pct)
                    else None
                )
                breadth_drop_now = self._session_breadth_drop(df)
                tape_confirms_downtrend = not (
                    # Money-tape recovery (Rule 5b) is computed above;
                    # where the rupees are going outranks the stale file.
                    money_tape_recovery
                    or recovery_mode
                    or (
                        live_breadth is not None
                        and live_breadth
                        >= self.config.recovery_breadth_pct
                        and (
                            breadth_drop_now is None
                            or breadth_drop_now
                            <= self.config.max_breadth_drop_pct
                        )
                    )
                )
                last = getattr(context, "index_last_close", None)
                sma = getattr(context, "index_sma", None)
                window = getattr(context, "index_window", self.config.index_sma_window)
                last_txt = f"{last:,.0f}" if isinstance(last, (int, float)) else "?"
                sma_txt = f"{sma:,.0f}" if isinstance(sma, (int, float)) else "?"
                reason = (
                    f"Rule 11: KSE-100 ({last_txt}) is below its "
                    f"{window}-session average ({sma_txt}) - market in "
                    f"downtrend, longs stand aside"
                )
                if not tape_confirms_downtrend:
                    # The tape disagrees with the file: the file is
                    # stale, the tape is now. Trade the day we are in
                    # under the normal gates - but a strong-horse
                    # exception is no longer needed to act.
                    pass
                elif self.config.strong_horse_enabled and strong_horse is None:
                    strong_horse = {
                        "gate": "Rule 11",
                        "reason": reason,
                        "index_last_close": last,
                        "index_sma": sma,
                        "index_window": window,
                    }
                elif not self.config.strong_horse_enabled:
                    return Decision(
                        action="STAND_ASIDE",
                        reason=reason,
                        timestamp=now,
                        metadata={
                            "regime": {
                                "index_last_close": last,
                                "index_sma": sma,
                                "index_window": window,
                                "tape_recovery": True,
                            },
                        },
                    )

        # --- Rule 11c: the live index tape (v2.1.0) -------------------------
        # Rule 11 reads END-OF-DAY history - it cannot see today. This
        # rule reads the KSE-100's LIVE session change, captured with
        # every snapshot (psx_core.broker_feed.parse_exs_message).
        # The owner's law: the index is the tide - when it is being sold
        # hard, most stocks are being sold with it, and an intraday long
        # would be swimming against every seller in the building.
        if context is not None and self.config.index_tape_enabled:
            idx_pct = getattr(context, "index_change_pct", None)
            if (
                isinstance(idx_pct, (int, float))
                and math.isfinite(idx_pct)
                and idx_pct <= self.config.index_tape_floor_pct
            ):
                return Decision(
                    action="STAND_ASIDE",
                    reason=(
                        f"Rule 11c: KSE-100 live tape {idx_pct:+.2f}% is at/below "
                        f"the {self.config.index_tape_floor_pct:+.2f}% floor - "
                        "a red index is selling most stocks with it; "
                        "longs stand aside"
                    ),
                    timestamp=now,
                    metadata={"index_change_pct": float(idx_pct)},
                )

        # --- Rule 12: foreign-flow regime (ADVISORY since v0.14.1) ------------
        # Was: a hard stand-aside veto. Proven misfire 2026-09-15: it
        # vetoed every cycle of a +1700-point rally because a lagging
        # 3-session flow sum (-7.34M, tail mostly noise) said "sell-off"
        # while the live tape said otherwise. The read is still computed
        # and still surfaced (regime metadata + engine property) - but
        # nothing here blocks on it. The tape gates entries now.

        # --- Rule 12b: institutional positioning ------------------------------
        # Hard gate only for the war signature (institutions distributing
        # to retail); FOMO is advisory. Dormant until the investor-type
        # history exists (load_context leaves these None).
        if context is not None and self.config.institutional_flow_enabled:
            inst_war = getattr(context, "inst_smart_retail_war", False)
            inst_fomo = getattr(context, "inst_retail_fomo", False)
            inst_foreign = getattr(context, "inst_foreign_net_usd", None)
            inst_inst = getattr(context, "inst_institutional_net_usd", None)
            inst_retail = getattr(context, "inst_retail_net_usd", None)
            regime_meta = {
                "inst_foreign_net_usd": inst_foreign,
                "inst_institutional_net_usd": inst_inst,
                "inst_retail_net_usd": inst_retail,
                "inst_retail_fomo": bool(inst_fomo),
                "inst_smart_retail_war": bool(inst_war),
                # Rule 12c (v0.16.2): pump/dump leaders, advisory.
                "inst_top_buyer": getattr(context, "inst_top_buyer", None),
                "inst_top_seller": getattr(context, "inst_top_seller", None),
            }
            self._inst_regime_meta = regime_meta
            if inst_war is True:
                # Belt and braces: the regime read carries its own
                # floor since v2.5.2; enforce here too so a stale
                # context can never reproduce the Sep-23 noise veto.
                side_ok = (
                    isinstance(inst_inst, (int, float))
                    and isinstance(inst_retail, (int, float))
                    and abs(inst_inst)
                    >= self.config.institutional_war_min_side_usd
                    and inst_retail
                    >= self.config.institutional_war_min_retail_usd
                )
                if not side_ok:
                    pass  # divergence below war size: advisory only
                else:
                    f_txt = (
                        f"{inst_foreign / 1e6:+.1f}M"
                        if isinstance(inst_foreign, (int, float))
                        else "?"
                    )
                    r_txt = (
                        f"{inst_retail / 1e6:+.1f}M"
                        if isinstance(inst_retail, (int, float))
                        else "?"
                    )
                    return Decision(
                        action="STAND_ASIDE",
                        reason=(
                            f"Rule 12b: institutions distributing to "
                            f"retail (inst {f_txt} USD vs retail "
                            f"{r_txt} USD net) - smart money handing "
                            "over stock at war size; stand aside"
                        ),
                        timestamp=now,
                        metadata={"regime": regime_meta},
                    )

        # --- Rule 13: opening sniper doctrine (v0.21.0) -----------------------
        minutes_since_open = self._minutes_since_open(latest_ts)
        if (
            minutes_since_open is not None
            and self.config.opening_hold_minutes > 0
            and minutes_since_open < self.config.opening_hold_minutes
        ):
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Rule 13: {minutes_since_open:.0f} min since open - "
                    f"opening auction chaos (first "
                    f"{self.config.opening_hold_minutes:.0f} min); the "
                    f"sniper window runs minutes "
                    f"{self.config.opening_hold_minutes:.0f}-"
                    f"{self.config.sniper_window_end_minutes:.0f}"
                ),
                timestamp=now,
                metadata={"minutes_since_open": round(minutes_since_open, 1)},
            )

        # --- Rule 13b: lunch doldrums --------------------------------------------
        # The dead drift between the morning leg and the close. Data,
        # not opinion: 450 panel candidates with forward paths show
        # 12:30-14:50 PKT entries win 5-10% of the time - the worst
        # hours of the PSX day. No entry fires here; exits keep working.
        pkt_minutes = self._pkt_minutes(latest_ts)
        if (
            self.config.no_entry_window_start_min > 0
            and pkt_minutes is not None
            and self.config.no_entry_window_start_min
            <= pkt_minutes
            < self.config.no_entry_window_end_min
        ):
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Rule 13b: lunch doldrums ({int(pkt_minutes) // 60:02d}:"
                    f"{int(pkt_minutes) % 60:02d} PKT is inside the banned "
                    f"{int(self.config.no_entry_window_start_min) // 60:02d}:"
                    f"{int(self.config.no_entry_window_start_min) % 60:02d}-"
                    f"{int(self.config.no_entry_window_end_min) // 60:02d}:"
                    f"{int(self.config.no_entry_window_end_min) % 60:02d} "
                    f"window - ledger shows 5-10% win rate in this "
                    f"stretch; no entries, exits unaffected"
                ),
                timestamp=now,
                metadata={"pkt_minutes": pkt_minutes},
            )

        # --- Rule 11b: breadth collapse -----------------------------------------
        # A level floor can pass a market that is collapsing through it.
        # This gate watches the shape: breadth this far below its own
        # intraday high means the open's strength is being unwound.
        breadth_drop = self._session_breadth_drop(df)
        if breadth_drop is not None and breadth_drop > self.config.max_breadth_drop_pct:
            current = None
            if breadth_pct is not None and pd.notna(breadth_pct):
                current = float(breadth_pct)
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Rule 11b: session breadth collapsed "
                    f"{breadth_drop:.1f} pts from its high"
                    + (
                        f" (now {current:.1f}%)"
                        if current is not None else ""
                    )
                    + " - sellers taking control, standing aside"
                ),
                timestamp=now,
                metadata={"breadth_drop_pts": round(breadth_drop, 1)},
            )

        # --- Build candidate pool -------------------------------------------
        candidates = self._filter_candidates(
            latest, held_symbols, context,
            strong_horse=strong_horse is not None,
            full_frame=df,
            recovery_mode=recovery_mode,
        )

        if candidates.empty:
            # Killer-gate summary: computed ONCE, always defined.
            trace = getattr(self, "_last_filter_trace", None) or []
            drops = [
                (name, prev - n)
                for (prev, (name, n)) in zip(
                    [t[1] for t in trace[:-1]], trace[1:]
                )
                if n < prev
            ]
            detail = ""
            if drops:
                top = sorted(drops, key=lambda d: d[1], reverse=True)[:3]
                detail = ", ".join(f"{name} -{n}" for name, n in top)
            suffix = f" (hardest gates: {detail})" if detail else ""

            if strong_horse is not None:
                reason = (
                    f"{strong_horse['reason']} - no strong horse "
                    f"(no candidate beating the tape by "
                    f"{self.config.strong_horse_min_outperformance_pct:.0f}+ pts "
                    "above VWAP), standing aside"
                )
            elif (
                context is not None
                and getattr(context, "index_below_sma", None) is True
                and self.config.index_regime_enabled
                and recovery_mode
            ):
                # Regime file says downtrend but recovery mode IS armed:
                # the tape (breadth/off-low/slope) overruled the file,
                # and the pool still emptied - the remaining gates
                # vetoed every candidate.
                reason = (
                    "Recovery day (file says downtrend, live tape says "
                    "recovery) - candidates not confirming fresh highs, "
                    "standing aside"
                ) + suffix
            else:
                # v0.17.9 honesty fix: the old message claimed
                # "recovery" even when recovery mode never armed - the
                # 2026-09-17 log said "recovery day" while the filter
                # ran ordinary floors (breadth-arm missed by 1 point).
                # Say what actually happened and why the mode is off.
                reason = (
                    "No eligible candidates after filtering - recovery "
                    "mode did NOT arm (needs off-low ≥ "
                    f"{self.config.recovery_min_off_low_pct:g}%, "
                    "30-min slope ≥ "
                    f"{self.config.recovery_slope_30m:g}%, or breadth ≥ "
                    f"{self.config.recovery_breadth_arm_pct:g}%) - "
                    "standing aside"
                ) + suffix
            return Decision(
                action="STAND_ASIDE",
                reason=reason,
                timestamp=now,
                metadata={
                    "held": sorted(held_symbols),
                    "strong_horse": strong_horse,
                },
            )

        # v3.2.0: the correlation-aware blocking gate is REMOVED by
        # owner's order. The one-call-per-day law already prevents
        # duplicate exposure; the gate was dead code in production.

        # --- Rule 9: circuit breaker (PSX-specific) ----------------------
        # In PSX, hitting the upper circuit (10% price band) is a
        # STRONG bullish signal, not a filter-out condition.
        # Some stocks (like PSYL) hit upper circuit with very low
        # volume - this is normal in PSX and means overwhelming
        # buying pressure on thin liquidity.
        #
        # We ONLY filter out TRULY FROZEN stocks: those where
        # the price hasn't moved across the last 12+ ticks at all.
        # A stock at upper circuit that is still trading (even at
        # low volume) is a valid long candidate - it is the
        # strongest possible trend signal in PSX.
        frozen_set = self._frozen_symbols(df, candidates)
        if frozen_set:
            candidates = candidates[~candidates["symbol"].isin(frozen_set)]

        # --- Rule 14b: sector cap --------------------------------------------
        # The book already owns this move: a second position in the same
        # sector is not diversification, it is the same trade twice
        # (2026-09-09 held NRL and ATRL - both refineries - an hour
        # apart). Held symbols' sectors come from the same frame slice.
        sector_capped: dict[str, str] = {}
        if (
            context is not None  # gates active only in live mode
            and self.config.sector_guard_enabled
            and self.config.max_positions_per_sector > 0
            and held_symbols
            and "sector" in candidates.columns
        ):
            held_sectors = (
                latest[latest["symbol"].isin(held_symbols)]
                .groupby("symbol")["sector"]
                .first()
                .dropna()
            )
            held_sector_counts = held_sectors.value_counts()
            if not held_sector_counts.empty:
                cap = int(self.config.max_positions_per_sector)
                for _, row in candidates.iterrows():
                    sec = row.get("sector")
                    if pd.isna(sec):
                        continue
                    if int(held_sector_counts.get(sec, 0)) >= cap:
                        sector_capped[str(row["symbol"])] = str(sec)
                if sector_capped:
                    candidates = candidates[
                        ~candidates["symbol"].isin(sector_capped)
                    ]

        if candidates.empty:
            reason = (
                "All top candidates blocked (frozen/sector-cap)"
                if frozen_set or sector_capped
                else "All top candidates blocked"
            )
            return Decision(
                action="STAND_ASIDE",
                reason=reason,
                timestamp=now,
                metadata={
                    "held": sorted(held_symbols),
                    "circuit_frozen": sorted(frozen_set or []),
                    "circuit_locked": sorted(frozen_set or []),
                    "sector_capped": sector_capped,
                },
            )

        # --- Pick the best --------------------------------------------------
        best = candidates.iloc[0]
        symbol = str(best["symbol"])

        # Prefer the z-score master score when it exists on the row; fall
        # back to the percentile composite. Both live in (0, 1).
        has_master = (
            self.config.prefer_master_score
            and "master_score" in best.index
            and pd.notna(best.get("master_score"))
        )
        if has_master:
            score = float(best["master_score"])
            score_kind = "master"
        else:
            score = float(best["feature_rank_score_adjusted"])
            score_kind = "rank"

        # v2.1.0 Rule 24: the gate sees the chase-penalized conviction.
        # The raw score stays in metadata; the ceiling veto (Rule 22)
        # still reads the RAW score - a penalty must never rescue an
        # extended extreme out of its own refusal.
        chase_pen = 0.0
        if "_chase_pen" in best.index and pd.notna(best.get("_chase_pen")):
            chase_pen = float(best["_chase_pen"])
        gate_score = max(0.0, score - chase_pen)

        # --- Conviction gate (the anti-forcing rule) ------------------------
        # An ENTER needs BOTH: a score above the effective gate AND enough
        # distinct evidence components behind it. Below either bar, the
        # cycle ends in STAND_ASIDE with the reason recorded - the bot
        # waits for a real signal instead of promoting the best of a
        # weak field. The gate may sit above the configured value when
        # the self-learning layer has tightened it after a bad stretch.
        min_score_gate = self.effective_min_master_score
        if strong_horse is not None:
            # A strong-horse entry needs even more conviction than a
            # normal day's - it is, by definition, a trade against the
            # tape and must clear a higher bar to be worth it.
            min_score_gate = max(
                min_score_gate, self.config.strong_horse_min_score
            )
        if gate_score < min_score_gate:
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Below conviction gate: best score {gate_score:.4f} "
                    f"(raw {score:.4f}, chase penalty {chase_pen:.3f}) < "
                    f"{min_score_gate:.2f} - no genuine "
                    f"signal yet, standing aside"
                ),
                timestamp=now,
                metadata={
                    "latest_timestamp": str(latest_ts),
                    "best_symbol": symbol,
                    "best_score": score,
                    "gate_score": gate_score,
                    "chase_penalty": chase_pen,
                    "score_kind": score_kind,
                    "gate": "min_master_score",
                    "gate_threshold": min_score_gate,
                    "candidates_considered": int(len(candidates)),
                },
            )

        evidence = self._evidence_count(best)
        if evidence < self.config.min_evidence_components:
            return Decision(
                action="STAND_ASIDE",
                reason=(
                    f"Thin evidence: {evidence} supporting components < "
                    f"{self.config.min_evidence_components} required - "
                    f"no genuine signal yet, standing aside"
                ),
                timestamp=now,
                metadata={
                    "latest_timestamp": str(latest_ts),
                    "best_symbol": symbol,
                    "best_score": score,
                    "score_kind": score_kind,
                    "gate": "min_evidence_components",
                    "evidence_count": evidence,
                    "candidates_considered": int(len(candidates)),
                },
            )

        # --- Rule 22: anti-predictive score ceiling (v0.18.0) -----------------
        # The 450-panel mine under the v0.18 exit policy: the engine's
        # own composite score is ANTI-predictive in its top tail -
        # candidates above 0.7 won 11.6% of forwards vs 29.5% below
        # (session-consistent 7/7). The score measures in-session
        # extension/rank, and the extreme names mean-revert into the
        # stop. Vetoed at the conviction layer, before sizing.
        if self.config.score_ceiling_veto and score is not None:
            try:
                if float(score) > self.config.score_ceiling:
                    return Decision(
                        action="STAND_ASIDE",
                        reason=(
                            f"Rule 22: composite score {float(score):.2f} > "
                            f"{self.config.score_ceiling:.2f} - the top tail "
                            f"of the score is anti-predictive (panel mine: "
                            f"11.6% vs 29.5% forward win rate); refusing "
                            f"the extended extreme"
                        ),
                        timestamp=now,
                        metadata={
                            "latest_timestamp": str(latest_ts),
                            "best_symbol": symbol,
                            "best_score": score,
                            "score_kind": score_kind,
                            "gate": "rule22_score_ceiling",
                            "score_ceiling": self.config.score_ceiling,
                            "candidates_considered": int(len(candidates)),
                        },
                    )
            except (TypeError, ValueError):
                pass

        price = float(best["price"]) if pd.notna(best.get("price")) else None

        # Rule 3: compute profit target. v2.1.0 pins the HIGH target:
        # the owner's real cost stack (broker both sides + SST + levies
        # + 15% CGT) puts breakeven near +0.85% per round trip. The
        # 450-panel grid searched every bracket against real forward
        # paths: TP 2.0/SL 1.5 needs a 67% win rate to break even -
        # nothing on this tape clears that - while TP 3.0/SL 1.0
        # breaks even at 46%, inside the range pullback-shaped entries
        # actually reach. The v0.9.0 low-target logic harvested pops
        # that no longer exist under the entry-shape fixes: entries no
        # longer chase, so the quick-pop premise is gone.
        profit_target_price = None
        profit_target_pct = None
        tp_kind = None
        if price is not None and price > 0:
            # Owner's universal law: every entry targets 2.0% - morning
            # and late alike. The old morning step-up to 3% is retired.
            minutes_in = self._minutes_since_open(latest_ts)
            low_t = max(self.config.profit_target_low, 0.0)
            high_t = max(self.config.profit_target_high, low_t)
            stepdown = max(self.config.tp_stepdown_minutes, 0.0)
            if stepdown > 0 and minutes_in is not None and minutes_in >= stepdown:
                profit_target_pct = low_t
                tp_kind = "floor"
            else:
                profit_target_pct = high_t
                tp_kind = "full"
            profit_target_price = round(price * (1.0 + profit_target_pct / 100.0), 2)

        # Position sizing: 10% of capital, rounded down to lot size (50 shares).
        quantity = None
        capital_alloc = None
        if price is not None and price > 0:
            alloc = self.capital * 0.10
            quantity = int(alloc // price)
            quantity = (quantity // 50) * 50  # round down to PSX lot of 50
            if quantity < 50:
                quantity = 0
            capital_alloc = round(quantity * price, 2)

        return Decision(
            action="ENTER" if quantity and quantity > 0 else "STAND_ASIDE",
            symbol=symbol if quantity and quantity > 0 else None,
            score=score if quantity and quantity > 0 else None,
            price=price if quantity and quantity > 0 else None,
            profit_target_price=profit_target_price if quantity and quantity > 0 else None,
            profit_target_pct=profit_target_pct if quantity and quantity > 0 else None,
            quantity=quantity if quantity and quantity > 0 else None,
            capital_alloc=capital_alloc if quantity and quantity > 0 else None,
            reason=(
                f"Conviction signal: {symbol} at {score:.4f} "
                f"({score_kind}, {evidence} components) @ {latest_ts}"
            ) if quantity and quantity > 0 else f"Insufficient capital for minimum lot (price={price})",
            timestamp=now,
            metadata={
                "latest_timestamp": str(latest_ts),
                "score_kind": score_kind if quantity and quantity > 0 else None,
                "evidence_count": evidence,
                # v2.1.0: raw vs gate score + the chase penalty that
                # produced the gap - stored per trade for the ledger.
                "best_score": score,
                "gate_score": gate_score,
                "chase_penalty": chase_pen,
                # v0.20.2: which target the card promised and why -
                # floor (2%, late entry) or full (3%, morning entry).
                "tp_pct": profit_target_pct,
                "tp_kind": tp_kind,
                # v0.21.0: where in the opening sniper doctrine this
                # entry sits. "auction"/"sniper"/"regular" - the ledger
                # grades whether the minute-15-20 pullback really is
                # the owner's sniper window.
                "opening_zone": (
                    "auction"
                    if minutes_since_open < self.config.opening_hold_minutes
                    else (
                        "sniper"
                        if minutes_since_open
                        <= self.config.sniper_window_end_minutes
                        else "regular"
                    )
                )
                if minutes_since_open is not None
                else None,
                "strong_horse": strong_horse,
                # v2.1.0: the chase context of the pick itself - how far
                # above the prior close it already sat at entry. The
                # portfolio stores this per trade so the ledger can be
                # mined feature-vs-outcome from now on.
                "entry_change_pct": (
                    float(best["change_pct"])
                    if "change_pct" in best.index
                    and pd.notna(best.get("change_pct"))
                    else None
                ),
                "breadth_pct": float(breadth_pct) if breadth_pct is not None and pd.notna(breadth_pct) else None,
                # v0.19.0: the earnings catalyst, when the pick just
                # published results - travels into the ledger so the
                # refit can learn what "fresh results + surge" is worth.
                "fresh_results": (
                    __import__("corporate_actions").fresh_results(
                        str(best["symbol"]), date.today(),
                        actions=self.corporate_actions,
                    )
                    if self.corporate_actions else None
                ),
                # v0.20.1: sessions of dividend-runway left when the
                # pick is inside its run-up (the owner rides the
                # chasers and dumps before the window). Absent = not
                # in any runway.
                "dividend_runway": (
                    __import__("corporate_actions").dividend_runway(
                        str(best["symbol"]), date.today(),
                        actions=self.corporate_actions,
                    )
                    if self.corporate_actions else None
                ),
                "candidates_considered": int(len(candidates)),
                "held_excluded": sorted(held_symbols),
                "sector_capped": sector_capped,
                "regime": {
                    "index_last_close": getattr(context, "index_last_close", None) if context is not None else None,
                    "index_sma": getattr(context, "index_sma", None) if context is not None else None,
                    "index_below_sma": getattr(context, "index_below_sma", None) if context is not None else None,
                    "foreign_flow_blocked": getattr(context, "foreign_flow_blocked", None) if context is not None else None,
                    "foreign_flow_streak": getattr(context, "foreign_flow_streak", None) if context is not None else None,
                    "foreign_flow_sum_usd": getattr(context, "foreign_flow_sum_usd", None) if context is not None else None,
                    "foreign_flow_advisory_only": True,
                    "inst_foreign_net_usd": getattr(context, "inst_foreign_net_usd", None) if context is not None else None,
                    "inst_institutional_net_usd": getattr(context, "inst_institutional_net_usd", None) if context is not None else None,
                    "inst_retail_net_usd": getattr(context, "inst_retail_net_usd", None) if context is not None else None,
                    "inst_retail_fomo": bool(getattr(context, "inst_retail_fomo", False)) if context is not None else False,
                    "inst_smart_retail_war": bool(getattr(context, "inst_smart_retail_war", False)) if context is not None else False,
                    "money_tape_recovery": money_tape_recovery,
                    "market_vw_change_pct": (
                        float(latest["market_vw_change_pct"].iloc[0])
                        if "market_vw_change_pct" in latest.columns
                        and pd.notna(latest["market_vw_change_pct"].iloc[0])
                        else None
                    ),
                    "market_vw_slope_30m": (
                        float(latest["market_vw_slope_30m"].iloc[0])
                        if "market_vw_slope_30m" in latest.columns
                        and pd.notna(latest["market_vw_slope_30m"].iloc[0])
                        else None
                    ),
                },
                "trend_filter": {
                    "enabled": self.config.trend_filter_enabled,
                    "vwap_ratio": (
                        float(best["vwap_ratio"])
                        if "vwap_ratio" in best.index
                        and pd.notna(best.get("vwap_ratio"))
                        else None
                    ),
                },
                "technical_indicators": {
                    "rsi14": (
                        float(best["rsi14"])
                        if "rsi14" in best.index
                        and pd.notna(best.get("rsi14"))
                        else None
                    ),
                    "ema_alignment": (
                        float(best["ema_alignment"])
                        if "ema_alignment" in best.index
                        and pd.notna(best.get("ema_alignment"))
                        else None
                    ),
                },
                "lessons_applied": {
                    "blacklisted": sorted(self.blacklisted),
                    "score_scale": bool(self.score_scale),
                    "gate_adjustment": self.min_master_score_adjustment,
                    "market_dead": sorted(self.market_dead_symbols),
                    "market_trending": sorted(self.market_trend_symbols),
                },
                "psx_circuit_breaker": {
                    # Upper circuit = strongest trend signal in PSX.
                    # A stock at +10% with 10,000 volume is a valid
                    # and strong long signal, not a filter-out.
                    "best_circuit_pct": (
                        float(best["circuit_breaker_pct"])
                        if "circuit_breaker_pct" in best.index
                        and pd.notna(best.get("circuit_breaker_pct"))
                        else None
                    ),
                    "change_pct": (
                        float(best["change_pct"])
                        if "change_pct" in best.index
                        and pd.notna(best.get("change_pct"))
                        else None
                    ),
                },
            },
        )

    @staticmethod
    def _evidence_count(row: pd.Series) -> int:
        """
        How many distinct evidence components back this candidate.

        Counts the non-NaN z_* master components on the row. When the
        master columns are absent entirely (early build, legacy frame),
        counts the non-NaN rank components instead - the answer degrades
        to a still-honest smaller number, never to a free pass.
        """
        z_columns = [c for c in row.index if str(c).startswith("z_")]
        if z_columns:
            return int(sum(1 for c in z_columns if pd.notna(row[c])))
        rank_columns = [c for c in row.index if str(c).startswith("rank_")]
        return int(sum(1 for c in rank_columns if pd.notna(row[c])))

    def _frozen_symbols(
        self,
        df: pd.DataFrame,
        candidates: pd.DataFrame,
    ) -> set[str]:
        """
        Rule 9 (PSX): candidates that are truly FROZEN - not
        trading at all.

        In PSX, upper circuit is NOT a freeze. A stock at upper
        circuit with even 10 shares traded is still actively
        trading and is the strongest trend signal possible.
        Only filter out stocks where the price hasn't moved at
        all across the last 12+ ticks - those are genuinely
        dead and can't be exited.
        """
        threshold = self.config.circuit_breaker_change_pct
        if "change_pct" not in df.columns or "price" not in df.columns:
            return set()

        frozen: set[str] = set()
        for symbol in candidates["symbol"].tolist():
            history = (
                df[(df["symbol"] == symbol) & df["tradable"]]
                .sort_values("timestamp")
                .tail(12)
            )
            if len(history) < 12:
                continue
            # A stock is frozen if it has traded fewer than 2
            # distinct prices in the last 12 ticks AND has not
            # moved more than 0.1% - completely dead tape.
            distinct_prices = history["price"].nunique()
            price_range = (
                history["price"].max() - history["price"].min()
            )
            last = history.iloc[-1]
            change = pd.to_numeric(
                last.get("change_pct"), errors="coerce"
            )
            # Only consider a stock frozen if it's at/near circuit
            # AND has zero price movement. A stock at upper circuit
            # that's still printing trades is NOT frozen.
            if pd.isna(change) or change < threshold:
                continue
            if distinct_prices <= 1 and price_range <= 0.01:
                frozen.add(str(symbol))
        return frozen

    @staticmethod
    def _pkt_minutes(latest_ts) -> int | None:
        """Minutes-of-day of the frame's latest timestamp in PKT.

        Used by Rule 13b (lunch doldrums). None when the timestamp
        cannot be parsed - the gate passes rather than blocking on an
        unknown clock, same convention as Rule 13.
        """
        try:
            from psx_core import sessions as _sessions

            ts = (
                latest_ts.to_pydatetime()
                if hasattr(latest_ts, "to_pydatetime") else latest_ts
            )
            local = _sessions.to_pkt(ts)
            return local.hour * 60 + local.minute
        except Exception:
            return None

    @staticmethod
    def _minutes_since_open(latest_ts) -> float | None:
        """
        Minutes between the PSX DAY's first scheduled open and the
        frame's latest timestamp (an aware datetime or pandas
        Timestamp; naive input is assumed UTC - the frame's
        convention).

        The noisy-open window applies only to the morning leg: the
        09:32 open auction is the noisy stretch. An afternoon leg
        (Friday 14:32) after the lunch break is NOT a fresh open -
        its first minutes carry orderly re-opening flow, and
        blocking them made the bot sleep through the exact window a
        lunch-base breakout fires (2026-09-11: the recovery
        afternoon the bot refused 14:32-15:02 while breadth ran
        from 44% to 51%).

        None when the schedule has no leg for that moment (holiday,
        weekend, --test on out-of-hours data): the morning-window
        gate passes rather than blocking on an unknown clock.
        """
        try:
            from psx_core import sessions as _sessions

            ts = (
                latest_ts.to_pydatetime()
                if hasattr(latest_ts, "to_pydatetime") else latest_ts
            )
            local = _sessions.to_pkt(ts)
            day_legs = _sessions.legs_for(local.date())
            if not day_legs:
                return None
            from datetime import datetime as _dt

            first_open = _dt.combine(
                local.date(), day_legs[0].start, tzinfo=_sessions.PKT
            )
            if local < first_open:
                return None
            return (local - first_open).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            return None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _session_breadth_drop(df: pd.DataFrame) -> float | None:
        """
        How many points session breadth has fallen from its intraday
        high (points, not percent-of-percent). Computed over the frame's
        breadth series per timestamp. None when breadth is missing or
        there is a single observation (nothing to collapse from).
        """
        if "breadth_pct" not in df.columns:
            return None
        series = (
            pd.to_numeric(df["breadth_pct"], errors="coerce")
            .groupby(df["timestamp"])
            .first()
            .dropna()
        )
        if len(series) < 2:
            return None
        high = float(series.max())
        last = float(series.iloc[-1])
        return max(0.0, high - last)

    def _filter_candidates(
        self,
        latest: pd.DataFrame,
        held_symbols: set[str],
        context: Any | None = None,
        *,
        strong_horse: bool = False,
        full_frame: pd.DataFrame | None = None,
        recovery_mode: bool = False,
    ) -> pd.DataFrame:
        """
        Apply all filtering rules to produce the eligible candidate pool,
        sorted by the preferred score descending (master z-score when
        available, else the percentile composite).

        strong_horse: the market tape is weak and only an exceptional
        candidate may pass - the outperformance and VWAP requirements
        below become hard (missing evidence is a fail, not a pass) and
        the same-day change cap is relaxed so a genuine runner is not
        disqualified for running.

        full_frame: the entire session frame behind `latest` - the
        Rule 16 freshness check reads each symbol's recent history
        from it. None (older callers, tests) skips the freshness
        check and judges the row's own columns only.
        """
        cfg = self.config
        c = latest.copy()
        trace: list[tuple[str, int]] = [("start", len(c))]

        def _step(frame: pd.DataFrame, name: str) -> pd.DataFrame:
            """Apply one filter stage and record its survivor count.

            When the pool empties, the empty-pool decision can name the
            stages that killed it (top killers in the reason) - no more
            post-mortems guessing which gate starved the engine.
            """
            nonlocal trace
            frame = frame.reset_index(drop=True)
            trace.append((name, len(frame)))
            return frame

        # Rule 1: must be tradable (quoted, open, real price).
        c = _step(c[c["tradable"] == True], "tradable")  # noqa: E712

        # Must have a score. The master score is optional - the percentile
        # composite remains the hard requirement.
        c = _step(c[c["feature_rank_score_adjusted"].notna()], "has_score")

        # Minimum score gate.
        if cfg.min_score > 0:
            c = _step(
                c[c["feature_rank_score_adjusted"] >= cfg.min_score],
                f"min_score>={cfg.min_score:g}",
            )

        # Minimum weight coverage.
        if "score_weight_coverage" in c.columns:
            c = _step(
                c[c["score_weight_coverage"] >= cfg.min_weight_coverage],
                "weight_coverage",
            )

        # Rule 6: exclude currently held symbols.
        if held_symbols:
            c = _step(c[~c["symbol"].isin(held_symbols)], "held_excluded")

        # Self-learning: symbols the lesson layer has blacklisted are
        # off the menu entirely (see src/lessons.py for the criteria).
        if self.blacklisted:
            c = _step(
                c[~c["symbol"].isin(self.blacklisted)], "blacklisted"
            )

        # v2.6.0 Rule 27 - the market-learner's confirmed-dead list.
        # A symbol dead (flat AND illiquid) 3+ sessions running has no
        # intraday fuel; the tape itself says so, daily, not a human.
        if self.market_dead_symbols:
            c = _step(
                c[~c["symbol"].isin(self.market_dead_symbols)],
                "market_dead",
            )

        # v0.20.1 Rule 25 - the owner's DIVIDEND-RUNWAY doctrine
        # (supersedes the v0.19.0 blanket veto). The goal is intraday
        # capital gain, never the dividend: weeks BEFORE the book-
        # closure window, dividend-chasers accumulate - real, persistent
        # demand we RIDE (PPL example: closure Oct 19 -> all of late Sep
        # is runway). Only the last 3 trading sessions before the
        # window/ex-date, the window itself, and the ex-date are fatal:
        # an entry there cannot be exited cleanly before the mechanical
        # drop. Missing corporate-actions data = no veto.
        if self.corporate_actions:
            import corporate_actions as ca

            today = date.today()
            blocks = [
                sym for sym in c["symbol"]
                if ca.book_closure_block(
                    sym, today, actions=self.corporate_actions
                )
            ]
            if blocks:
                c = _step(c[~c["symbol"].isin(blocks)], "book_closure")

        # Rule 10: trend filter - "the trend is your friend". Enter
        # only stocks trading above the session VWAP. (v3.1.1: the
        # Kalman trend floor is REMOVED from the rulebook by owner's
        # order - the filter now rests on price-vs-VWAP evidence only.
        # Missing columns are a pass: the filter never invents
        # evidence, it only refuses when the evidence says no.)
        if cfg.trend_filter_enabled:
            if cfg.require_above_vwap and "vwap_ratio" in c.columns:
                c = _step(
                    c[c["vwap_ratio"].isna() | (c["vwap_ratio"] >= 0.0)],
                    "above_vwap",
                )

        # --- Strong-horse requirements (weak-tape days only) -----------------
        # The gates above defer on a weak tape only so that a candidate
        # proving this much can still trade: beating the market's median
        # change by the configured margin, trending hard, above VWAP.
        # Unlike every other filter these are HARD requirements - on a
        # day when the tape is against us, missing evidence is a fail.
        if strong_horse and "change_pct" in c.columns:
            market_median = pd.to_numeric(
                latest["change_pct"], errors="coerce"
            ).median()
            if pd.isna(market_median):
                c = _step(c.iloc[0:0], "strong_horse_no_median")
            else:
                needed = market_median + cfg.strong_horse_min_outperformance_pct
                c = _step(
                    c[
                        pd.to_numeric(c["change_pct"], errors="coerce")
                        >= needed
                    ],
                    "strong_horse_outperform",
                )
                if "vwap_ratio" in c.columns:
                    c = _step(
                        c[c["vwap_ratio"] >= 0.0], "strong_horse_vwap"
                    )

        # Rule 4: no chasing - reject extended symbols. Strong-horse mode
        # allows a wider same-day move (the whole point: the 2-10%
        # runners weak days still produce), still below the circuit.
        change_cap = (
            cfg.strong_horse_max_same_day_change_pct
            if strong_horse else cfg.max_same_day_change_pct
        )
        if recovery_mode:
            # The stocks leading a V-recovery are up big on the day by
            # definition - the normal cap rejects the tape's own leaders
            # (PRL +6.5% on Rs 4.5bn during the 2026-09-11 recovery).
            # Still capped, just wider, and still below the circuit.
            change_cap = max(change_cap, cfg.recovery_max_day_change_pct)
        if "change_pct" in c.columns:
            c = _step(
                c[c["change_pct"].abs() <= change_cap],
                f"day_change<={change_cap:g}",
            )

        # Hard floor 2 (v0.5.0): no RED-tape longs. A long intraday
        # signal on a stock that is red on the day is a bet that today's
        # sellers are wrong; both such entries in the ledger (CNERGY,
        # BUXL on red prints) stopped out. Flat-on-day passes - it is
        # not contradicting evidence, and the engine's rule is that
        # missing evidence passes, contradicting evidence fails.
        if cfg.require_positive_day_change and "change_pct" in c.columns:
            c = _step(c[c["change_pct"] >= 0], "day_change>=0")

        # Hard floor 3 (v0.5.0): no bounce-chasing. The ledger's worst
        # loss (BUXL, score 0.773 - the highest conviction the bot has
        # ever printed) entered +9.5% off its day low while red: a
        # dead-cat bounce that looked like strength. Every winner
        # entered within +1.8% of its low. Recovery mode relaxes the
        # cap (a recovering board is by definition off its lows), it
        # does not remove it.
        if "distance_from_low_pct" in c.columns:
            off_low_cap = (
                cfg.recovery_max_entry_off_low_pct
                if recovery_mode
                else cfg.max_entry_off_low_pct
            )
            if off_low_cap > 0:
                c = _step(
                    c[
                        c["distance_from_low_pct"].isna()
                        | (c["distance_from_low_pct"] <= off_low_cap)
                    ],
                    f"off_low<={off_low_cap:g}",
                )

        # Rule 25: chase hard veto (v2.2.0) - the +8%-over-prior-close
        # cohort won 6.9% of forwards at -2.18% net across the 450-panel
        # simulation, unrescuable by any exit config in the grid. Hard
        # filter, not a demotion. Missing day-change passes.
        if cfg.chase_hard_veto_enabled and "change_pct" in c.columns:
            prem25 = pd.to_numeric(c["change_pct"], errors="coerce")
            c = _step(
                c[prem25.isna() | (prem25 < cfg.chase_veto_max_change_pct)],
                f"chase_veto<{cfg.chase_veto_max_change_pct:g}",
            )

        # Rule 26 (v2.4.0): the low-conviction green-open ban. The
        # 175-session grind (backtest_grind4.py) measured the entry
        # family the live book kept taking - a mild green day (0-2%)
        # with a green open - at 13.4% wins, -0.79% net per trade,
        # losing in EVERY month of 2026 (10-15% win in 8 of 9). PPL
        # 2026-09-21 (score 0.623, day +0.79%) is the type case. The
        # data is unambiguous: without lock-class momentum, a sub-2%
        # green day does not pay for its own costs. Candidates inside
        # the dead band are refused unless the conviction gate would
        # pass them anyway (score floor kept high for the escape hatch),
        # and the whole rule is config-switchable for the refit loop.
        # Missing day-change passes (the gate never invents a veto).
        if (
            cfg.dead_zone_veto_enabled
            and "change_pct" in c.columns
        ):
            dz = pd.to_numeric(c["change_pct"], errors="coerce")
            in_dead_zone = (dz >= 0) & (dz < cfg.dead_zone_max_change_pct)
            # Escape hatch: a candidate whose conviction already clears
            # the dead-zone ceiling is not refused - the refit loop can
            # tighten it later, and a genuinely strong tape earns its
            # shot. Score column: master when present, rank otherwise.
            # A MISSING score never hardens the veto (same doctrine as
            # the missing day-change above: the gate never invents
            # evidence). Missing day-change rows stay in the pool.
            score_col = (
                "master_score"
                if "master_score" in c.columns
                else (
                    "score"
                    if "score" in c.columns
                    else (
                        "feature_rank_score_adjusted"
                        if "feature_rank_score_adjusted" in c.columns
                        else None
                    )
                )
            )
            if score_col:
                sc = pd.to_numeric(c[score_col], errors="coerce")
                strong = (sc >= cfg.dead_zone_max_score).fillna(False)
                in_dead_zone = in_dead_zone & ~strong
            # Grind-6 escape hatch: symbols whose 175-session lock
            # record is proven (win >= 70%, n >= 8 - BTL 87% n=23,
            # KPUS 84.6% n=39, ITANZ 83.3% n=24, OML 83.3% n=18,
            # FIL 92.9% n=14) pass the dead zone even below the
            # ceiling: their per-stock base rate beats the pool.
            if self.lock_memory_symbols and "symbol" in c.columns:
                in_dead_zone = in_dead_zone & ~c["symbol"].isin(
                    self.lock_memory_symbols
                ).fillna(False)
            # v2.5.1 Rule 26b: chronic lock-fakes are banned outright,
            # wherever they sit in the band (dead zone included - the
            # exemption list and the ban list never overlap by
            # construction: win >= 70% vs win < 50%).
            if self.lock_banned_symbols and "symbol" in c.columns:
                c = _step(
                    c[~c["symbol"]
                        .isin(self.lock_banned_symbols)
                        .fillna(False)],
                    "rule26b_lock_fake_ban",
                )
                # Recompute the dead-zone mask on the narrowed frame so
                # the ban and the dead zone never fight over a row.
                if len(c) and "change_pct" in c.columns:
                    dz = pd.to_numeric(c["change_pct"], errors="coerce")
                    in_dead_zone = (dz >= 0) & (
                        dz < cfg.dead_zone_max_change_pct
                    )
                    if score_col:
                        sc = pd.to_numeric(c[score_col], errors="coerce")
                        in_dead_zone = in_dead_zone & ~(
                            sc >= cfg.dead_zone_max_score
                        ).fillna(False)
                    if self.lock_memory_symbols:
                        in_dead_zone = in_dead_zone & ~c["symbol"].isin(
                            self.lock_memory_symbols
                        ).fillna(False)
            # No score column: the mask itself already excludes NaN
            # day-change rows ((NaN >= 0) & (NaN < x) is False), so a
            # missing change_pct passes untouched.
            c = _step(
                c[in_dead_zone.isna() | ~in_dead_zone],
                f"dead_zone_ban<{cfg.dead_zone_max_change_pct:g}%_low_conviction",
            )

        # Rule 24: chase penalty (v2.1.0) - demote, don't ban. How far
        # above the prior close the candidate already sits at this
        # poll is stored per candidate; the sort key below subtracts
        # it (a fresh pullback outranks a chased spike) and the
        # conviction gate sees the penalized score. STL 2026-09-18 is
        # the type case: bought at +2.2% over the prior close, the
        # 2% TP needed a +4.2% day, the tape mean-reverted to flat.
        if len(c):
            if "change_pct" in c.columns:
                prem = pd.to_numeric(c["change_pct"], errors="coerce")
                c = c.assign(
                    _chase_pen=(
                        (prem - 1.0) * cfg.chase_penalty_per_pct
                    )
                    .clip(lower=0.0)
                    .fillna(0.0)
                    .clip(upper=cfg.chase_penalty_cap)
                )
            else:
                c = c.assign(_chase_pen=0.0)

        # Rule 14a: sector guard - a stock trending up inside a sector
        # being dumped is fighting the tape. ATRL on 2026-09-10
        # "trended up" at 10:03 while refineries averaged -3.5%; it was
        # one tick from its stop two hours later. Sector means come
        # from the full latest slice (every quoted member), not just
        # the candidate pool. Missing sector data is a pass.
        if (
            cfg.sector_guard_enabled
            and "sector" in c.columns
            and "change_pct" in latest.columns
        ):
            sector_means = (
                pd.to_numeric(latest["change_pct"], errors="coerce")
                .groupby(latest["sector"])
                .mean()
                # zscore-style helper not needed; plain means per sector.
                # Members without a sector (NaN key) never appear here.
            )
            row_sector_mean = c["sector"].map(sector_means)
            c = _step(
                c[
                    row_sector_mean.isna()
                    | (row_sector_mean >= -abs(cfg.sector_guard_max_drop_pct))
                ],
                "sector_guard",
            )

        # Rule 15: multi-day extension - Rule 4 only sees today. A
        # candidate up more than the scaled threshold over its recent
        # daily closes is a chase, whatever today's change says
        # (ECOP, 2026-09-10: +4% cap respected on the day, +19% over
        # the week, stopped out by 11:00). Symbols without 3+ stored
        # closes are not judged.
        if context is not None and cfg.max_multi_day_gain_pct > 0:
            closes_map = getattr(context, "daily_closes", None) or {}
            # Empty-pool guard: DataFrame.apply(f, axis=1) on a zero-row
            # frame returns an empty non-bool Series, and masking with it
            # strips EVERY column from `c` - the sort key below then dies
            # with a KeyError instead of the engine standing aside
            # gracefully. (Surfaced by the replay harness, 2026-09-11;
            # reachable live whenever the strong-horse filters empty the
            # pool on a weak tape.) Nothing to filter -> skip the block.
            if closes_map and not c.empty:
                from market_regime import multi_day_gain

                def _extended(row: pd.Series) -> bool:
                    closes = closes_map.get(str(row["symbol"]))
                    if not closes:
                        return False
                    result = multi_day_gain(closes, row.get("price"))
                    if result is None:
                        return False
                    gain, sessions_used = result
                    threshold = cfg.max_multi_day_gain_pct * sessions_used / 5.0
                    return bool(gain > threshold)

                c = _step(
                    c[~c.apply(_extended, axis=1)], "multi_day_extension"
                )

        if "price_position_range" in c.columns:
            c = _step(
                c[
                    c["price_position_range"].notna()
                    & (c["price_position_range"] <= cfg.max_price_position)
                ],
                "price_position",
            )

        # Rule 8: liquidity floor (T1.5) - the day's traded value must
        # support a clean intraday exit. `value` is the cumulative day
        # total in the feed; missing value fails the floor conservatively.
        if cfg.min_day_value > 0 and "value" in c.columns:
            c = _step(
                c[c["value"].fillna(0) >= cfg.min_day_value],
                f"day_value>={cfg.min_day_value:g}",
            )

        # Rule 27: penny-stock floor (v4.2.1) - sub-Rs-10 names
        # (KEL 6-7) print fake calls on thin tapes. Missing price
        # fails closed; the strong horse is not exempt (a Rs-6
        # rocket is still untradeable cleanly).
        if "price" in c.columns:
            price = pd.to_numeric(c["price"], errors="coerce")
            c = _step(
                c[price.notna() & (price >= cfg.min_entry_price)],
                f"price>={cfg.min_entry_price:g}",
            )

        # Rule 18: overbought veto (v0.17.0) - never buy statistical
        # exhaustion. RSI >= max_entry_rsi is the blow-off chase the
        # ledger punishes; missing RSI passes (no invented evidence).
        if cfg.max_entry_rsi < 100 and "rsi14" in c.columns:
            rsi_v = pd.to_numeric(c["rsi14"], errors="coerce")
            c = _step(
                c[rsi_v.isna() | (rsi_v < cfg.max_entry_rsi)],
                f"rsi<{cfg.max_entry_rsi:g}",
            )

        # Rule 19: stretch veto REMOVED (v3.1.1, owner's order) - the
        # Bollinger %B band no longer vetoes entries. Rule 20
        # (divergence veto) REMOVED v3.2.0 - not on the whitelist.

        # Rule 17: follow the money - where are today's rupees going?
        # sector_money_flow_pct is the sector's live share of the
        # market's traded value vs its typical share. Below the floor
        # = the market's own money is avoiding this sector; a long
        # there is a bet against the flow. Missing column = pass
        # (never invents evidence).
        if (
            cfg.min_sector_money_flow > 0
            and "sector_money_flow_pct" in c.columns
            and not recovery_mode
        ):
            # Skipped in recovery mode: the EWMA flow baseline is still
            # anchored to the morning's crash weights for ~40 minutes,
            # so the sectors LEADING the recovery read artificially low
            # (the 15:15+ steps of 2026-09-11 - survivors 11 -> 2 -> 0).
            # The money-tape detector already vouched for the market;
            # the per-sector gate re-arms the moment recovery ends.
            c = _step(
                c[
                    c["sector_money_flow_pct"].isna()
                    | (
                        c["sector_money_flow_pct"]
                        >= cfg.min_sector_money_flow
                    )
                ],
                "sector_money_flow(skipped:recovery)",
            )

        # Rule 16b: buyer presence - the live book must not be
        # ask-stacked at entry. bid_volume >= this fraction of
        # ask_volume: buyers visibly willing to absorb, not a
        # "trend" being distributed into retail hands (the
        # 2026-09-10 shape: prices up, ask side swollen). An empty
        # ask side (ask == 0, no sellers queued) passes by
        # definition - it is the most bullish book there is; a
        # missing/unreadable book carries no evidence and passes.
        if cfg.min_bid_ask_balance > 0 and {"bid_volume", "ask_volume"} <= set(c.columns):
            bid = pd.to_numeric(c["bid_volume"], errors="coerce")
            ask = pd.to_numeric(c["ask_volume"], errors="coerce")
            balance_ok = (
                (ask.isna() | (ask <= 0))          # no readable sellers
                | (
                    bid.notna()
                    & ask.notna()
                    & (ask > 0)
                    & (bid >= cfg.min_bid_ask_balance * ask)
                )
            )
            c = _step(c[balance_ok], "bid_ask_balance")

        # Rule 16: confirmation - read, don't predict.
        # A candidate may only enter when it is STILL PRESSING toward
        # its session high at this very poll: the buy side is present
        # now, not an hour ago. The 2026-09-10 losers "trended" on
        # stale evidence while fading far off their highs. Reading the
        # tape honestly:
        #   * price within confirmation_at_high_pct of the session
        #     high - a strong stock breathes 1-3% intraday; a 0.75%
        #     band refused PRL at +6.5% on Rs. 4.5bn value during
        #     the 2026-09-11 recovery because it was 2% off its
        #     morning spike (2026-09-11);
        #   * the high is FRESH - it made a new session high within
        #     the last confirmation_fresh_minutes, so the move is
        #     still developing rather than decaying (the 09-10 ATRL
        #     entry bought a morning high that was 90 minutes stale);
        #   * positive 1-minute momentum at this poll.
        # Missing columns = no readable confirmation = no entry.
        if cfg.confirmation_enabled and (
            "high" in c.columns or recovery_mode
        ):
            # `high` is only read when present: recovery-mode confirmation
            # anchors to the recent-window price max from full_frame and
            # never touches the column (a synthetic recovery frame
            # without `high` used to KeyError here).
            high = (
                pd.to_numeric(c["high"], errors="coerce")
                if "high" in c.columns else None
            )
            price = pd.to_numeric(c["price"], errors="coerce")
            mom_ok = None
            if "momentum_1m_pct" in c.columns:
                mom = pd.to_numeric(c["momentum_1m_pct"], errors="coerce")
                mom_ok = mom.notna() & (mom > 0)

            if (
                recovery_mode
                and full_frame is not None
                and {"price", "timestamp"} <= set(full_frame.columns)
            ):
                # Recovery-day confirmation. On a V-day the DAY high is
                # the morning spike's top - hours stale by the afternoon
                # leg - so anchoring "pressing the high" to it refuses
                # every honest recoverer (the 2026-09-11 15:15+ steps:
                # survivors 11 -> 2 -> 0). The recovery-mode anchor is
                # the RECENT window: price within the confirmation band
                # of its max traded price over the last
                # recovery_recent_high_minutes, still above where it
                # traded recovery_rise_lookback_minutes ago (rising,
                # not a dead bounce), positive 1-minute momentum.
                frame_latest_ts = full_frame["timestamp"].max()
                rec_cut = frame_latest_ts - pd.Timedelta(
                    minutes=float(cfg.recovery_recent_high_minutes)
                )
                rise_cut = frame_latest_ts - pd.Timedelta(
                    minutes=float(cfg.recovery_rise_lookback_minutes)
                )
                rec = full_frame[full_frame["timestamp"] >= rec_cut]
                if rec.empty:
                    confirmed = pd.Series(False, index=c.index)
                else:
                    rec_high = rec.groupby("symbol")["price"].max()
                    pre = full_frame[full_frame["timestamp"] <= rise_cut]
                    p_then = (
                        pre.sort_values("timestamp")
                        .groupby("symbol")["price"]
                        .last()
                        if not pre.empty else pd.Series(dtype=float)
                    )
                    rh = c["symbol"].map(rec_high)
                    p0 = c["symbol"].map(p_then)
                    from_rh = (1.0 - price / rh) * 100.0
                    confirmed = (
                        rh.notna() & price.notna() & (rh > 0)
                        & (from_rh <= cfg.confirmation_at_high_pct)
                        # Missing rise reference (first ticks of a leg,
                        # thin prints) passes - no evidence either way;
                        # a readable, LOWER reference price fails.
                        & (p0.isna() | (price >= p0 - 1e-9))
                    )
                    if mom_ok is not None:
                        # Recovery mode: a 1-min momentum print needs a
                        # trade in the trailing 60s. During a V-recovery
                        # even the leaders print every few minutes, so
                        # NaN here means "no recent trade", not "not
                        # rising" - and requiring it refused the whole
                        # board (2026-09-11 15:15: every top scorer
                        # NaN). Missing evidence passes; CONTRADICTING
                        # evidence (finite and falling) still fails.
                        confirmed &= (
                            mom_ok | mom.isna()
                        ) if "momentum_1m_pct" in c.columns else mom_ok
            else:
                # Normal-day confirmation (unchanged).
                # Distance from the session high, in percent.
                from_high_pct = (1.0 - price / high) * 100.0
                # The day must actually be moving: a stock trading at its
                # (flat) high with no range is locked, not confirmed.
                readable = high.notna() & price.notna() & (high > 0)
                confirmed = (
                    readable
                    & (from_high_pct <= cfg.confirmation_at_high_pct)
                )
                if mom_ok is not None:
                    confirmed &= mom_ok
                # Fresh-high check: the session high must have ADVANCED
                # within the freshness window - the feed's `high` column
                # is the cumulative day high on every row, so "does the
                # recent window contain the max" is always true and says
                # nothing. The honest read: compare the high NOW against
                # the high as the window OPENED (the last snapshot before
                # the cutoff). A high above that advanced inside the
                # window - a live move; a high identical to it is an old
                # spike being reclaimed. Pressing AT the high right now
                # (price == high) is fresh by definition.
                if (
                    confirmed.any()
                    and full_frame is not None
                    and {"high", "timestamp"} <= set(full_frame.columns)
                ):
                    frame_latest_ts = full_frame["timestamp"].max()
                    cutoff = frame_latest_ts - pd.Timedelta(
                        minutes=float(cfg.confirmation_fresh_minutes)
                    )
                    window = full_frame[full_frame["timestamp"] >= cutoff]
                    pre = full_frame[full_frame["timestamp"] < cutoff]
                    if not window.empty:
                        if not pre.empty:
                            baseline = (
                                pre.sort_values("timestamp")
                                .groupby("symbol")["high"]
                                .last()
                            )
                        else:
                            baseline = pd.Series(dtype=float)
                        # Symbols whose whole session started inside the
                        # window (resumed from suspension, late listing):
                        # their baseline is their first in-window print.
                        win_first = (
                            window.sort_values("timestamp")
                            .groupby("symbol")["high"]
                            .first()
                        )
                        baseline = (
                            baseline.reindex(win_first.index)
                            .fillna(win_first)
                        )
                        row_baseline = c["symbol"].map(baseline)
                        confirmed &= row_baseline.notna() & (
                            (high > row_baseline + 1e-9)
                            | (price >= high - 1e-9)
                        )
                    else:
                        confirmed &= False
            c = c[confirmed]

        # Rule 2: we return the full sorted list; the caller picks one.
        # Sort key: master z-score when preferred and present, falling
        # back per-row to the percentile composite when master is
        # missing on that row. The self-learning score_scale (when
        # fitted) rescales the key so consistently profitable scores
        # rank slightly higher and consistently overconfident ones
        # slightly lower - a nudge on the ordering, never a bypass of
        # the conviction gate.
        if cfg.prefer_master_score and "master_score" in c.columns:
            key = c["master_score"].fillna(c["feature_rank_score_adjusted"])
        else:
            key = c["feature_rank_score_adjusted"]
        # v2.1.0: the chase penalty demotes the pool ordering too -
        # the engine evaluates the TOP candidate, so a penalized
        # spike must fall through to the next-best fresh name
        # instead of dead-ending the cycle on a chase.
        if "_chase_pen" in c.columns:
            key = key - c["_chase_pen"].fillna(0.0)
        scale = self.score_scale if isinstance(self.score_scale, dict) else None
        if scale:
            try:
                slope = float(scale["slope"])
                center = float(scale["center"])
                key = key * (1.0 + slope * (key - center))
            except (KeyError, TypeError, ValueError):
                pass  # malformed lesson: rank unscaled
        c = c.assign(_sort_key=key).sort_values("_sort_key", ascending=False)
        c = c.drop(columns="_sort_key")

        # Persist the funnel for the decision metadata: an empty pool
        # can name its killers, a healthy pool keeps its audit trail.
        self._last_filter_trace = trace
        return c.head(cfg.candidate_pool_size)
