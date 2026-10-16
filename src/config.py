"""Single source of truth for Quant of Rehan configuration (rebuild 2026-10-09).

Rebuild rule (owner, 2026-10-09): every tunable in the rebuilt system lives
in this one module. No other module may hardcode a threshold, a target, a
coverage floor or a trade limit.

The market clock is deliberately NOT redefined here: Asia/Karachi UTC+5 and
the session windows come from src/data/sessions.py, which is the one
authoritative Karachi definition (SO-8). This module re-exports them so a
caller has a single import surface, and never builds a market time itself.

Environment overrides exist so a scheduled job can flip a flag without a
code change; every default is the safe one (paper only, live off).
"""

from __future__ import annotations

import os

from src.data.sessions import (
    FRIDAY_CLOSE,
    FRIDAY_OPEN,
    KARACHI,
    WEEKDAY_CLOSE,
    WEEKDAY_OPEN,
)

# ---------------------------------------------------------------- market clock
MARKET_TIMEZONE = "Asia/Karachi"
MARKET_OPEN_MON_THU = WEEKDAY_OPEN        # (9, 32) Karachi
MARKET_CLOSE_MON_THU = WEEKDAY_CLOSE      # (15, 30) Karachi
MARKET_OPEN_FRIDAY = FRIDAY_OPEN          # (9, 17) Karachi
MARKET_CLOSE_FRIDAY = FRIDAY_CLOSE        # (16, 30) Karachi
MARKET_TZINFO = KARACHI                   # the only timezone object in use


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------- hard limits
PAPER_TRADING_ENABLED = _flag("PAPER_TRADING_ENABLED", True)
LIVE_TRADING_ENABLED = _flag("LIVE_TRADING_ENABLED", False)
MAX_TRADES_PER_DAY = 1

# The one signal a Karachi day is allowed, enforced where it can actually be
# enforced. A local state file (src/signals/trade_state.py) is a per-machine
# lock; the cloud runs a band loop plus scheduled backstop slots, each starting
# from a restored copy of the day's state, so two runs can both decide to enter
# and emit two accepted BUY candidates for the same day. The relay's
# /research/claim is the one shared answer to "is today's signal already
# spoken for", and scripts/intraday_pipeline.run_scan asks it before entering.
# Kept as a switch for one reason: with the relay unreachable the claim fails
# closed (no entry, reported), and an owner who wants paper observation to
# continue without the relay can turn the requirement off deliberately.
SIGNAL_CLAIM_REQUIRED = _flag("SIGNAL_CLAIM_REQUIRED", True)
TARGET_PCT = _number("TARGET_PCT", 2.0) / 100.0
KMIALL_ONLY = True
LONG_ONLY = True

# ---------------------------------------------------------------- data quality
# Coverage floor for a real scan. Below it the scan is DATA_BLOCKED, never a
# market verdict (owner spec section 8 and 29).
MIN_COVERAGE_PCT = _number("MIN_COVERAGE_PCT", 0.80)
# Retired as a blocking floor on 2026-10-15: measured 74.9% to 78.7% on the
# real tapes, so a whole-universe freshness floor blocked every live scan (see
# MIN_RANKABLE_SHARE). The number is still reported in every quality report and
# still recorded in the snapshot, and freshness is still blocking, but on the
# leaders and the rankable population rather than on the illiquid tail.
MIN_FRESH_COVERAGE_PCT = _number("MIN_FRESH_COVERAGE_PCT", 0.80)
STALENESS_MINUTES = _number("STALENESS_MINUTES", 5.0)
MAX_MALFORMED_SHARE = _number("MAX_MALFORMED_SHARE", 0.01)
BAR_RESOLUTION = "1-minute"

# One minute, in seconds: the grid BAR_RESOLUTION names, and the bucket size
# the tape bar builder writes (src/data/tape_bars.py). Kept as a number so the
# builder never parses the label above.
BAR_SECONDS = _number("BAR_SECONDS", 60.0)

# How much of the captured universe must carry enough bars to be judged at
# all. score_symbol already refuses a symbol with fewer than
# MIN_BARS_PER_SYMBOL bars, so a capture thinner than this share would produce
# an empty ranking, and an empty ranking that is really a short capture would
# be reported as a market NO TRADE. This floor makes that case a DATA BLOCKED
# with the measured bar count, which is what it is (SO-3).
#
# It is measured only where a ranking is possible: a capture younger than
# MIN_BARS_PER_SYMBOL minutes cannot hold that many bars in ANY symbol, so it
# is a warm-up (see WARMUP_GRACE_MINUTES below) rather than a data failure.
MIN_HISTORY_COVERAGE_PCT = _number("MIN_HISTORY_COVERAGE_PCT", 0.30)
# Owner order 2026-10-15 raised on the previous 0.80 default: measured live, a
# working 301-symbol tape held the 20 bars the strategy needs on 213 symbols
# (70.8%), and the floor blocked the scan anyway. A ranking already refuses
# any symbol with fewer than MIN_BARS_PER_SYMBOL bars, and the rankable
# population gates (MIN_RANKABLE_SYMBOLS / MIN_RANKABLE_SHARE) decide where a
# ranking would say nothing useful about the market, so the whole-universe
# history share is now a degeneracy tripwire (a tape so thin that under 30%
# of captured symbols grew 20 bars) and a measured REPORT on every scan, not
# a whole-scan block. The rest of the universe is ranked, not refused.

# -------------------------------------------------------------------------
# The rankable population (redesign 2026-10-15).
#
# Measured before this change, on the real session tapes the cloud recorded
# (data/feed_capture/capture_20261013.ndjson, 314 symbols, 4h of tape) and on
# the live band logs of 2026-10-14 (run 38530614304: 88 cycles, 87 scans, all
# DATA_BLOCKED):
#
#   * freshness across the WHOLE 319 symbol KMIALL universe peaks at 74.9% to
#     78.7% inside five minutes, because roughly a fifth of KMIALL prints less
#     often than once every five minutes. The 80% whole-universe freshness
#     floor was therefore unreachable on real data, so every live scan of the
#     session was DATA_BLOCKED and no signal could ever exist.
#   * the population the strategy actually ranks and enters from (the volume
#     leaders) was fresh in 19 or 20 of every 20 leaders at every instant
#     measured, and 212 to 245 symbols were both fresh and deep enough to be
#     scored.
#
# So freshness and depth are judged on the symbols a ranking can use, and the
# illiquid tail is REPORTED with its count instead of blocking the scan for
# every symbol (SO-3: named, never hidden). MIN_COVERAGE_PCT still measures
# the whole universe, because "did the market trade today" is a whole-universe
# question.
MIN_RANKABLE_SYMBOLS = int(_number("MIN_RANKABLE_SYMBOLS", 60))
# And the share of what the capture actually saw. A market is unrankable when
# the rankable population is BOTH small in absolute terms and a thin slice of
# the captured universe; either test alone would block a small, healthy
# capture (a two symbol test universe ranks perfectly well). Measured on the
# real tape: rankable is 66% to 77% of the universe and 72% to 85% of the
# captured symbols, so 50% keeps a wide margin.
MIN_RANKABLE_SHARE = _number("MIN_RANKABLE_SHARE", 0.50)

# The leader slice: the top N symbols by session traded value, which is where
# a candidate can actually come from. These must be fresh, or the ranking is
# reading prices that stopped moving.
LEADER_SLICE = int(_number("LEADER_SLICE", 20))
MIN_LEADER_FRESH_SHARE = _number("MIN_LEADER_FRESH_SHARE", 0.80)

# A capture younger than this is warming up, not broken: no symbol can hold
# MIN_BARS_PER_SYMBOL one-minute bars before MIN_BARS_PER_SYMBOL minutes of
# tape exist. Reported as a data block with the minutes still needed, and the
# runner pauses on it instead of counting a fault.
WARMUP_GRACE_MINUTES = int(_number("WARMUP_GRACE_MINUTES", 20))

# ---------------------------------------------------------------- scanner
# Window lengths in minutes, oldest first.
MOMENTUM_WINDOWS = (5, 15, 30)
VOLUME_WINDOW = 5
MIN_BARS_PER_SYMBOL = 20

# Half-credit scale for each saturating component: the value at which the
# component earns 0.5. Chosen as "meaningful but not extraordinary" on KMIALL.
HALF_CREDIT_MOMENTUM_FAST = _number("HALF_CREDIT_MOMENTUM_FAST", 0.004)
HALF_CREDIT_ACCELERATION = _number("HALF_CREDIT_ACCELERATION", 0.002)
HALF_CREDIT_REL_VOLUME = _number("HALF_CREDIT_REL_VOLUME", 1.0)
HALF_CREDIT_VOLUME_ACCEL = _number("HALF_CREDIT_VOLUME_ACCEL", 1.0)
HALF_CREDIT_TRADED_VALUE = _number("HALF_CREDIT_TRADED_VALUE", 20_000_000.0)

# Component weights, in the order they are reported. They sum to 1.0 and are
# asserted below, so the score can never silently drift.
SCORE_WEIGHTS = {
    "momentum": 0.32,
    "acceleration": 0.24,
    "relative_volume": 0.20,
    "volume_acceleration": 0.14,
    "liquidity": 0.10,
}

MIN_SIGNAL_SCORE = _number("MIN_SIGNAL_SCORE", 55.0)
MIN_RELATIVE_VOLUME = _number("MIN_RELATIVE_VOLUME", 1.5)
MIN_VOLUME_ACCEL_RATIO = _number("MIN_VOLUME_ACCEL_RATIO", 1.0)
MIN_SESSION_TRADED_VALUE = _number("MIN_SESSION_TRADED_VALUE", 5_000_000.0)
MAX_SESSION_EXTENSION = _number("MAX_SESSION_EXTENSION", 0.06)
MAX_DISTANCE_FROM_HIGH = _number("MAX_DISTANCE_FROM_HIGH", 0.01)
MIN_PRICE = _number("MIN_PRICE", 1.0)
EXTENSION_PENALTY_POINTS = _number("EXTENSION_PENALTY_POINTS", 15.0)
WEAKNESS_PENALTY_POINTS = _number("WEAKNESS_PENALTY_POINTS", 10.0)

# ---------------------------------------------------------------- market gate
MIN_BREADTH = _number("MIN_BREADTH", 0.35)
MAX_MARKET_DROP = _number("MAX_MARKET_DROP", -0.01)

# ---------------------------------------------------------------- universe
# ETFs are excluded from EVERY scan: they are basket instruments tracking an
# index or a commodity and are not made for intraday trading (owner order
# 2026-10-15). The KMIALL snapshot carries two of them (MIIETF, MZNPETF) as
# Shariah constituents, so they are filtered at load, by name and by the
# exchange's own naming convention, never by guessing from prices.
EXCLUDE_ETFS = _flag("EXCLUDE_ETFS", True)
ETF_SYMBOL_SUFFIX = "ETF"
EXCLUDED_ETF_SYMBOLS = frozenset({"MIIETF", "MZNPETF"})


def is_etf_symbol(symbol: str) -> bool:
    """True when *symbol* is an exchange-traded fund.

    Kept as the short answer for callers that only need this one question, and
    answered by src/data/eligibility.py so there is exactly one ETF rule in the
    project: the reviewed registry first, then the exchange's naming
    convention. The two names below are mirrored in the registry with their
    source and review date, and the suffix test is the same rule the service
    applies, so this function and that service can never disagree.
    """
    from src.data import eligibility  # local: eligibility reads config lazily

    return eligibility.is_etf(symbol)

SCANNER_VERSION = "momentum_volume_acceleration_v1"

# ---------------------------------------------------------------- volatility
# Session volatility regime, measured from the captured bars
# (src/signals/volatility.py). The regime is REPORTED with every scan. The two
# levers below are OFF by default so the live strategy is unchanged until the
# owner turns them on: VOLATILITY_AWARE_TARGETS scales the +2% target by
# TARGET_MULTIPLIER_BY_REGIME, and VOLATILITY_VETO_ENABLED refuses names that
# could not have been filled at all (a limit-locked print with no volume).
ATR_CALM_PCT = _number("ATR_CALM_PCT", 0.0025)
ATR_ELEVATED_PCT = _number("ATR_ELEVATED_PCT", 0.0075)
ATR_EXTREME_PCT = _number("ATR_EXTREME_PCT", 0.0200)
MAX_GAP_PCT = _number("MAX_GAP_PCT", 0.05)
MAX_INTRADAY_SWING_PCT = _number("MAX_INTRADAY_SWING_PCT", 0.10)
VOLATILITY_AWARE_TARGETS = _flag("VOLATILITY_AWARE_TARGETS", False)
VOLATILITY_VETO_ENABLED = _flag("VOLATILITY_VETO_ENABLED", False)
TARGET_MULTIPLIER_BY_REGIME = {
    "CALM": _number("TARGET_MULT_CALM", 0.8),
    "NORMAL": _number("TARGET_MULT_NORMAL", 1.0),
    "ELEVATED": _number("TARGET_MULT_ELEVATED", 1.25),
    "EXTREME": _number("TARGET_MULT_EXTREME", 1.5),
    "UNKNOWN": 1.0,
}

# ---------------------------------------------------------------- scheduler
# The local tick (scripts/kmiall_tick.py). Task Scheduler fires every
# TICK_INTERVAL_MINUTES all day; the tick itself pauses outside the session, so
# a dumb scheduler fire costs nothing. TICK_WARMUP_MINUTES keeps the runner from
# scanning before the strategy's own minimum bar and volume-bucket requirements
# can be met (MIN_BARS_PER_SYMBOL is 20 and VOLUME_WINDOW is 5).
#
# Owner order 2026-10-11: scan the whole KMIALL universe every 4 minutes,
# forever until further notice, and never in the pre-market (09:00-09:15) or
# post-market (15:32-15:49, Friday 16:32-16:49) windows. The 4 is the default
# here, so a rebuilt task or a fresh clone runs at 4 minutes without any
# environment change; the tick itself refuses to scan outside MARKET
# (src/data/sessions.py, is_scan_window).
TICK_INTERVAL_MINUTES = _number("TICK_INTERVAL_MINUTES", 4)
TICK_WARMUP_MINUTES = _number("TICK_WARMUP_MINUTES", 20)

# SO-13 (owner order 2026-10-14): "make the repo public but then i want the
# quant of rehan to be scanned every 30 seconds". One scan serves both the
# phone's card and the intraday paper strategy, so this is the cadence of the
# supervised session loop the cloud job runs, and the slot width its
# once-per-slot guard is keyed on. The local 4-minute tick keeps its own
# TICK_INTERVAL_MINUTES: the two are different runners, not two cadences for
# one runner. Measured cost of one cycle on the real 2026-10-13 session tape
# (44.6 MB, 314 symbols): 2.9s to build, load, gate and rank, inside a 30s slot.
SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 30)
TICK_STALE_LOCK_MINUTES = _number("TICK_STALE_LOCK_MINUTES", 15)

# How long the broker venue may push NO market data at all before the recorder
# treats the session as stalled and reconnects.
#
# Measured 2026-10-16, inside the live Friday band: two separate fresh
# connections were each answered with exactly ONE full sweep of the universe
# (32 MKT-FEED frames carrying 315 rows) and then nothing. One stall ran for
# five consecutive minutes (10:06 to 10:10) before the sweeps returned at 64
# frames a minute; re-sending the subscription frame on the same socket did
# NOT restore the stream (probe: 32 frames after the first subscribe, 0 frames
# in the 60 seconds after re-subscribing), but a NEW connection is answered
# with a fresh sweep every time. The 2026-10-13 session tape never went a
# single minute below 31 frames, so a twenty second silence is not a quiet
# market, it is a stalled push: the recorder now stops waiting rather than
# letting the tape age out and block every later scan as stale.
TICK_STALL_SECONDS = _number("TICK_STALL_SECONDS", 20.0)

# The bar capture is ONE polite, sequential pass over the universe
# (src/data/ohlc_poller.py). The 319 symbol KMIALL universe needs about seven
# minutes at the source's own 1.3s pacing, and no timeout can make that faster.
# Owner order 2026-10-11 fixes the cadence at 4 minutes, so the capture is given
# the cadence minus a reserve for the scan that follows it, and it stops CLEANLY
# at that budget instead of being killed. Before this, every tick on a trading
# day logged "capture timed out after 240s" against a pass that needed about
# 415s: the limit was smaller than the work.
CAPTURE_BUDGET_SECONDS = _number("CAPTURE_BUDGET_SECONDS", 0)   # 0 = derive
CAPTURE_BUDGET_RESERVE_SECONDS = _number("CAPTURE_BUDGET_RESERVE_SECONDS", 45)
#: Backstop only: a capture that ignores its own budget is killed after the
#: budget plus this margin, so a wedged pass can never hold the tick lock.
CAPTURE_KILL_MARGIN_SECONDS = _number("CAPTURE_KILL_MARGIN_SECONDS", 90)

# The tape bar builder (src/data/tape_bars.py) fills a minute the venue was
# quiet in with the previous close, because that is a market fact: no trade
# happened and the running counter did not move. The fill is bounded by this
# gap: two consecutive observations further apart than this are an outage or a
# stopped tape, not a quiet market, so the series is left with a hole instead
# of a flat invented line. Measured on the 2026-10-13 KMIALL tape, the feed
# observes a symbol about every 30 seconds (median gap 30.0s, p90 150s), so
# five minutes is far above its normal cadence and far below an outage.
TAPE_CARRY_MAX_GAP_SECONDS = _number("TAPE_CARRY_MAX_GAP_SECONDS", 300.0)

# ---------------------------------------------------------------- session gate
# The sleep gate (src/data/session_gate.py) is the first question a scheduled
# job asks. Outside the session it must cost seconds, so it runs before any
# dependency install or heavy fetch and does no network work of its own.
SESSION_GATE_ENABLED = _flag("SESSION_GATE_ENABLED", True)

# ---------------------------------------------------------------- PSX probe
# The live portal probe (src/data/market_probe.py) VERIFIES the session law and
# never replaces it: the law decides, the probe may only subtract confidence.
# One bounded request, a strict timeout, no retries. Any failure degrades to
# UNKNOWN so a blocked portal can never silence a live session, and a positive
# "closed" reading can never be scanned as if it were open. The timeout is a
# config tunable rather than a literal so a scheduled job can tighten it
# without a code change.
PSX_PROBE_ENABLED = _flag("PSX_PROBE_ENABLED", True)
PSX_PROBE_TIMEOUT_SECONDS = _number("PSX_PROBE_TIMEOUT_SECONDS", 10.0)
PSX_PROBE_MAX_BYTES = int(_number("PSX_PROBE_MAX_BYTES", 400_000))
PSX_PROBE_URL = (os.environ.get("PSX_PROBE_URL", "").strip()
                 or "https://dps.psx.com.pk/")

# ---------------------------------------------------------------- AI signal
# The AI component (src/signals/ai_model.py) is a trained DAILY prior: the
# probability that a symbol touches +2% before -0.5% within 10 sessions. It is
# a different horizon from the intraday rule, so it is wired in as a bounded
# PRIOR and never as a hidden decision: recorded per candidate, used to break a
# near-tie between the top two rule scores, and optionally to veto the weakest
# sliver of the model's own distribution. AI_TIE_BAND is the rule-score gap
# inside which the prior may reorder; outside it the rule score wins outright.
AI_SIGNAL_ENABLED = _flag("AI_SIGNAL_ENABLED", True)
AI_TIE_BREAK_ENABLED = _flag("AI_TIE_BREAK_ENABLED", True)
AI_TIE_BAND = _number("AI_TIE_BAND", 2.0)
# The veto is OFF by default: the fitted edge is weak (holdout AUC ~0.56), so
# the honest default is to record the prior without letting it refuse a signal.
AI_GATE_ENABLED = _flag("AI_GATE_ENABLED", False)
AI_REJECT_PERCENTILE = _number("AI_REJECT_PERCENTILE", 0.25)
MODEL_FILE = "models/kmiall_signal_v1.json"

# ---------------------------------------------------------------- cost model
# Single source of truth for execution costs. The frozen research gate
# (src/research/forward_validation.py) and the live paper cycle both read
# these numbers, so "net return" means exactly one thing everywhere. Live
# trading is off, so these are paper accounting only: PSX commission, the
# 16% sales tax on commission, levies, modelled slippage and 15% CGT on
# positive net returns (owner's cost schedule, 2026-10-07).
COST_SIDE_BPS = _number("COST_SIDE_BPS", 22.4)
SLIPPAGE_SIDE_BPS = _number("SLIPPAGE_SIDE_BPS", 10.0)
CGT_RATE = _number("CGT_RATE", 0.15)

# ---------------------------------------------------------------- storage
SESSION_STATE_FILE = "data/forward/session_state.json"
SESSION_JOURNAL_FILE = "data/forward/session_journal.jsonl"
OBSERVATION_FILE = "data/forward/observation.json"
DAILY_OUTCOME_FILE = "data/forward/daily_outcome.json"
PRODUCTION_GATE_FILE = "data/forward/production_gate.json"

assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, "score weights must sum to 1.0"
assert 0.0 <= CGT_RATE < 1.0, "CGT rate must be a fraction"


def round_trip_cost() -> float:
    """Total modelled cost of a round trip, as a fraction of entry value:
    both sides at COST_SIDE_BPS plus both sides of slippage."""
    return 2.0 * (COST_SIDE_BPS + SLIPPAGE_SIDE_BPS) / 10000.0


def net_return(gross_return: float | None) -> float | None:
    """Net return after round-trip costs and CGT on a positive result.

    Mirrors the frozen research gate exactly (src/research/forward_validation
    .label_candidate) so a paper outcome and a research label agree. A None
    input stays None: an unvalued position is never given a made-up net.
    """
    if gross_return is None:
        return None
    net = float(gross_return) - round_trip_cost()
    if net > 0:
        net *= 1.0 - CGT_RATE
    return round(net, 6)


def live_trading_enabled() -> bool:
    """Live trading is off unless the owner sets the environment flag AND the
    paper gate is already on. Nothing in this repository can place an order."""
    return bool(LIVE_TRADING_ENABLED and not PAPER_TRADING_ENABLED)


# The three owner confirmations a session must carry before its evidence may
# count toward production. The band workflows already pass them
# (intraday-session.yml, intraday-capture.yml) but nothing in the code read
# them, so the gate's production_data_ready check had no input at all and
# could only ever be false (found 2026-10-16). Read here, once, so the session
# record and the gate answer the same question from the same source.
DATA_RIGHTS_CONFIRMED_ENV = "KMIALL_DATA_RIGHTS_CONFIRMED"
DATA_LATENCY_CONFIRMED_ENV = "KMIALL_DATA_LATENCY_CONFIRMED"
UNIVERSE_CONFIRMED_ENV = "KMIALL_UNIVERSE_CONFIRMED"


def data_confirmations() -> dict:
    """The owner's own data confirmations for this run, as booleans.

    Each one is an explicit statement by the owner that the underlying claim
    holds (rights to the feed, measured latency, universe currentness). They
    are read, never assumed: an unset variable is False, and a False value is
    carried into the session record so the production gate can refuse to
    count that session rather than guess that it was verified.
    """
    return {
        "data_rights_confirmed": _flag(DATA_RIGHTS_CONFIRMED_ENV, False),
        "data_latency_confirmed": _flag(DATA_LATENCY_CONFIRMED_ENV, False),
        "universe_confirmed": _flag(UNIVERSE_CONFIRMED_ENV, False),
    }


def production_data_ready(confirmations: dict | None = None) -> bool:
    """All three confirmations present. The frozen gate's own definition."""
    state = data_confirmations() if confirmations is None else confirmations
    return all(bool(state.get(key)) for key in (
        "data_rights_confirmed", "data_latency_confirmed",
        "universe_confirmed"))


def config_snapshot() -> dict:
    """Honest, loggable view of the configuration in force."""
    return {
        "timezone": MARKET_TIMEZONE,
        "open_mon_thu": list(MARKET_OPEN_MON_THU),
        "close_mon_thu": list(MARKET_CLOSE_MON_THU),
        "open_friday": list(MARKET_OPEN_FRIDAY),
        "close_friday": list(MARKET_CLOSE_FRIDAY),
        "target_pct": round(TARGET_PCT * 100, 4),
        "max_trades_per_day": MAX_TRADES_PER_DAY,
        "min_coverage_pct": MIN_COVERAGE_PCT,
        "min_signal_score": MIN_SIGNAL_SCORE,
        "min_relative_volume": MIN_RELATIVE_VOLUME,
        "min_session_traded_value": MIN_SESSION_TRADED_VALUE,
        "score_weights": dict(SCORE_WEIGHTS),
        "scanner_version": SCANNER_VERSION,
        "ai_signal_enabled": AI_SIGNAL_ENABLED,
        "ai_tie_break_enabled": AI_TIE_BREAK_ENABLED,
        "ai_tie_band": AI_TIE_BAND,
        "ai_gate_enabled": AI_GATE_ENABLED,
        "ai_reject_percentile": AI_REJECT_PERCENTILE,
        "model_file": MODEL_FILE,
        "atr_thresholds_pct": [ATR_CALM_PCT, ATR_ELEVATED_PCT, ATR_EXTREME_PCT],
        "max_gap_pct": MAX_GAP_PCT,
        "max_intraday_swing_pct": MAX_INTRADAY_SWING_PCT,
        "volatility_aware_targets": VOLATILITY_AWARE_TARGETS,
        "volatility_veto_enabled": VOLATILITY_VETO_ENABLED,
        "bar_resolution": BAR_RESOLUTION,
        "bar_seconds": BAR_SECONDS,
        "min_history_coverage_pct": MIN_HISTORY_COVERAGE_PCT,
        "min_rankable_symbols": MIN_RANKABLE_SYMBOLS,
        "min_rankable_share": MIN_RANKABLE_SHARE,
        "leader_slice": LEADER_SLICE,
        "min_leader_fresh_share": MIN_LEADER_FRESH_SHARE,
        "warmup_grace_minutes": WARMUP_GRACE_MINUTES,
        "tape_carry_max_gap_seconds": TAPE_CARRY_MAX_GAP_SECONDS,
        "paper_trading_enabled": PAPER_TRADING_ENABLED,
        "live_trading_enabled": live_trading_enabled(),
        "session_gate_enabled": SESSION_GATE_ENABLED,
        "psx_probe_enabled": PSX_PROBE_ENABLED,
        "psx_probe_timeout_seconds": PSX_PROBE_TIMEOUT_SECONDS,
        "tick_interval_minutes": TICK_INTERVAL_MINUTES,
        "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
        "tick_stall_seconds": TICK_STALL_SECONDS,
        "signal_claim_required": SIGNAL_CLAIM_REQUIRED,
        "kmiall_only": KMIALL_ONLY,
        "long_only": LONG_ONLY,
        "data_confirmations": data_confirmations(),
    }
