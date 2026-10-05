"""
PSX KMIALL BOT
Market regime - "be with the market, not against it."

The 2026-09-10 session made the gap visible: the engine's per-stock
trend filter (Rule 10) happily signed off on CNERGY, ECOP and ATRL at
09:40-10:03 PKT while the market itself was 70% red and the KSE-100 sat
5% below its monthly trend. All three stopped out. The per-stock
checks answer "is THIS stock rising?"; nothing answered "is the MARKET
worth being long right now?".

This module builds the market-level context the decision engine gates
on. Every input degrades to None/unknown on missing or stale data - a
gate only refuses when its evidence is actually present (the same
philosophy as Rule 10: never invent evidence, only respect it).

Four regime inputs, all cheap, all PSX-native:

  index_trend      KSE-100 last close vs its 20-session average
                   (data/kse100_history.json, src/fetch_index_history.py).
                   The single strongest "is this market long-able" test.
  breadth_floor    % of universe advancing (feature frame, Rule 5) -
                   threshold raised 30 -> 40: every loss so far entered
                   at breadth <= 32.7%, both wins at >= 45.6%.
  breadth_collapse session-high breadth minus current breadth - catches
                   the open-strong-then-roll-over shape (31.6% -> 17%
                   on 2026-09-10) before the floor does.
  foreign_flow     NCCPL foreign net: streak of net-sell sessions is
                   the documented driver of the Aug-Sep 2026 correction.
                   Dormant until 3 sessions of history accumulate.

Plus the multi-day extension check (no chasing a stock that already ran
while the "no chasing" rule only saw today): daily closes from
data/daily_closes.json (fresh tail) merged with the positive-open scan's
DPS cache data/processed/psx_eod_history.json (depth).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from psx_core import paths

# --- Pure state functions (unit-tested without any files) ------------------


def index_regime_state(
    rows: list[dict] | None,
    window: int = 20,
) -> dict:
    """
    Index trend verdict from stored KSE-100 rows
    ([{"date": date, "close": float}], oldest first).

    Returns {} when there is not enough history; otherwise
    {"last_close", "sma", "below_sma", "pct_vs_sma", "window"}.
    below_sma is the gate input: True = the index is below its average =
    the market is in a downtrend and longs stand aside.
    """
    closes = [float(r["close"]) for r in (rows or []) if r.get("close")]
    if len(closes) < window + 1:
        return {}
    last = closes[-1]
    sma = sum(closes[-window:]) / window
    if sma <= 0:
        return {}
    return {
        "last_close": last,
        "sma": sma,
        "below_sma": last < sma,
        "pct_vs_sma": (last / sma - 1.0) * 100.0,
        "window": window,
    }


def foreign_flow_state(
    history: list[dict] | None,
    streak_days: int = 3,
    min_net_usd: float = -5_000_000.0,
) -> dict:
    """
    Foreign-flow verdict from daily history rows
    ([{"date": str, "net_total_usd": float}], oldest first).

    Blocks only when the LAST `streak_days` sessions are ALL net selling
    AND their sum breaches min_net_usd (default -$5M over 3 sessions -
    an emphatic exodus, not ordinary two-way flow). Anything less, or a
    shorter history, yields blocked=False: the gate waits for real
    evidence.
    """
    nets = [
        float(r["net_total_usd"])
        for r in (history or [])
        if r.get("net_total_usd") is not None
    ]
    if len(nets) < streak_days:
        return {"blocked": False, "streak": 0, "sum_usd": None,
                "sessions": len(nets)}
    tail = nets[-streak_days:]
    all_selling = all(n < 0 for n in tail)
    total = sum(tail)
    return {
        "blocked": bool(all_selling and total <= min_net_usd),
        "streak": streak_days if all_selling else _sell_streak(nets),
        "sum_usd": total,
        "sessions": len(nets),
    }


def _sell_streak(nets: list[float]) -> int:
    """Length of the trailing run of consecutive net-sell sessions."""
    streak = 0
    for n in reversed(nets):
        if n < 0:
            streak += 1
        else:
            break
    return streak


# Investor classes NCCPL tracks, split into the two behavioural camps
# the bot cares about: institutions/smart money versus the retail crowd.
INSTITUTIONAL_INVESTORS = (
    "Foreign",
    "Mutual Funds",
    "Banks / DFI",
    "Insurance",
    "NBFC",
)
RETAIL_INVESTORS = ("Individuals",)


def institutional_state(
    history: list[dict] | None,
    *,
    fomo_ratio: float = 1.35,
    divergence_ratio: float = 2.0,
    min_sessions: int = 3,
    min_net_usd: float = 2_000_000.0,
    war_min_side_usd: float = 10_000_000.0,
    war_min_retail_usd: float = 1_000_000.0,
) -> dict:
    """
    Institutional verdict from the per-session history rows (oldest
    first). Rows without "byInvestor" (pre-matrix or legacy) are
    skipped for investor-level reads but still count for the foreign
    streak via their net_total_usd.

    Three reads:

      foreign_net_usd      -- latest session's foreign net (the
                              documented PSX correction driver).
      retail_fomo          -- latest session's Individuals net divided
                              by the average of the previous
                              min_sessions-1 retail nets, when positive
                              and above `fomo_ratio`. Retail piling in
                              while institutions are net SELLING is
                              the classic late-stage distribution
                              signature (Sep 2026: individuals +$50M
                              over 19 sessions while foreign bled
                              -$26M) - a score-blunting regime, never
                              a crash signal on its own.
      smart_retail_war     -- institutions net selling at least
                              `war_min_side_usd` (real distribution,
                              not noise) while retail net buys more
                              than `divergence_ratio` times as hard
                              and at least `war_min_retail_usd` of
                              genuine participation. The size floor on
                              the SELL side is the fix for the Sep-23
                              all-day veto: -2.2M vs +0.3M is rounding
                              noise, not a war - the same
                              lagging-flow-kills-a-rally misfire the
                              v0.14.1 lesson documented. PSX retail
                              nets ~2-3M/session on average, so the
                              retail floor stays at participation
                              level; the institution side carries the
                              magnitude bar.
    """
    rows = [r for r in (history or []) if isinstance(r, dict)]
    out = {
        "foreign_net_usd": None,
        "retail_net_usd": None,
        "institutional_net_usd": None,
        "retail_fomo": False,
        "smart_retail_war": False,
        "sessions": len(rows),
    }

    latest = rows[-1] if rows else None
    by_inv = (latest or {}).get("byInvestor") or {}
    if by_inv:
        foreign_net = (by_inv.get("Foreign") or {}).get("net")
        retail_net = (by_inv.get("Individuals") or {}).get("net")
        inst_net = sum(
            float((by_inv.get(name) or {}).get("net") or 0.0)
            for name in INSTITUTIONAL_INVESTORS
        )
        out["foreign_net_usd"] = (
            float(foreign_net) if foreign_net is not None else None
        )
        out["retail_net_usd"] = (
            float(retail_net) if retail_net is not None else None
        )
        out["institutional_net_usd"] = inst_net

        # Retail FOMO: retail net buy vs its own recent baseline.
        retail_rows = [
            float(((r.get("byInvestor") or {}).get("Individuals") or {}).get("net") or 0.0)
            for r in rows[:-1]
        ][-max(1, min_sessions - 1):]
        if (
            isinstance(retail_net, (int, float))
            and retail_net > 0
            and retail_rows
        ):
            baseline = sum(retail_rows) / len(retail_rows)
            if baseline >= 0:
                out["retail_fomo"] = bool(
                    baseline < 1.0 and retail_net >= min_net_usd
                    or retail_net >= fomo_ratio * max(baseline, 1.0)
                )

        # Smart-retail war: institutions selling SIZE while retail
        # absorbs. The institution side must clear war_min_side_usd
        # (a dump worth blocking a session over); retail must clear
        # war_min_retail_usd (real participation, not a rounding
        # error). Sep-23's -2.2M vs +0.3M fails both bars: noise.
        if (
            isinstance(retail_net, (int, float))
            and inst_net < 0
            and retail_net > 0
            and abs(inst_net) >= divergence_ratio * max(retail_net, 1.0)
            and abs(inst_net) >= war_min_side_usd
            and retail_net >= war_min_retail_usd
        ):
            out["smart_retail_war"] = True

        # Rule 12c (v0.16.2) - pump/dump leaders: WHICH institution is
        # buying hardest and which is dumping hardest this session.
        # 2026-09-15 evidence: on every day the book traded, Mutual
        # Funds were net sellers (-2.9M..-7.3M) and the one flat-MF
        # day was the only non-negative one - a lead that Foreign-only
        # reads (Rule 12) cannot see. Advisory: surfaced in every
        # decision's regime metadata and in SIGNALS.md, never a veto
        # on its own (the v0.14.1 lesson: lagging flow must not
        # override the live tape).
        nets = [
            (name, float(v.get("net") or 0.0))
            for name, v in by_inv.items()
            if isinstance(v, dict)
        ]
        if nets:
            buyer, buyer_net = max(nets, key=lambda nv: nv[1])
            seller, seller_net = min(nets, key=lambda nv: nv[1])
            out["top_buyer"] = {"name": buyer, "net_usd": buyer_net}
            out["top_seller"] = {"name": seller, "net_usd": seller_net}
    elif rows:
        # Legacy rows: keep the foreign read alive from net_total_usd.
        out["foreign_net_usd"] = latest.get("net_total_usd")

    return out


def append_foreign_flow_history(snapshot: dict, data_date: str) -> bool:
    """
    Fold one institutional-flow snapshot (the fetcher's persisted dict)
    into data/foreign_flow_history.jsonl as:

      {"date", "net_total_usd",
       "byInvestor": {name: {"buy", "sell", "net"}},
       "matrix": {investor: {sector: net}}}

    `byInvestor` comes from the page's "By investor type" table -
    COMPLETE every session (the per-sector table drops inactive
    sectors, and the pre-v0.10.0 rows summed the *cumulative-window*
    page instead of the session: both bugs fixed here).

    The snapshot reflects the session named by `data_date` (NCCPL
    publishes after close). Idempotent per date: re-fetching the same
    session replaces its line instead of duplicating it. Returns True
    when the file changed.
    """
    by_investor = snapshot.get("netByInvestorUsd") or {}
    foreign_net = (by_investor.get("Foreign") or {}).get("net")
    if foreign_net is None:
        # Legacy shape (pre-matrix fetcher): fall back to the sector sum.
        flows = snapshot.get("foreignNetBySectorUsd") or {}
        values = [v for v in flows.values() if isinstance(v, (int, float))]
        foreign_net = float(sum(values)) if values else None
    if foreign_net is None or not data_date:
        return False
    total = float(foreign_net)

    matrix = snapshot.get("netMatrixUsd") or {}
    record: dict = {"date": data_date, "net_total_usd": total}
    if by_investor:
        record["byInvestor"] = by_investor
    if matrix:
        record["matrix"] = matrix
    record_json = json.dumps(record, ensure_ascii=False)
    path = paths.DATA_DIR / "foreign_flow_history.jsonl"
    lines: list[str] = []
    if path.exists():
        lines = [
            ln for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    # Replace an existing line for the same date, else append.
    kept = [
        ln for ln in lines
        if not (ln.strip().startswith("{") and f'"date": "{data_date}"' in ln)
    ]
    kept.append(record_json)
    kept.sort(key=lambda ln: _line_date(ln))
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True


def _line_date(line: str) -> str:
    try:
        return str(json.loads(line).get("date", ""))
    except json.JSONDecodeError:
        return ""


def multi_day_gain(
    closes: list[float],
    price: float,
    *,
    max_sessions: int = 5,
    min_sessions: int = 3,
) -> tuple[float, int] | None:
    """
    Gain of `price` over the last k stored closes (k <= max_sessions),
    or None when fewer than min_sessions closes exist.

    The caller compares the gain against a threshold scaled by k/max -
    a 15%-over-5-sessions standard becomes ~9% over 3, so ECOP-style
    +19% three-day runs are caught on either span.
    """
    closes = [c for c in (closes or []) if c and c > 0]
    if len(closes) < min_sessions or not price or price <= 0:
        return None
    k = min(max_sessions, len(closes))
    base = closes[-k]
    if base <= 0:
        return None
    return (price / base - 1.0) * 100.0, k


def merge_daily_closes(
    dps_cache: dict[str, list] | None,
    records: dict[str, dict[str, float]] | None,
    before_date: str,
) -> dict[str, list[float]]:
    """
    Merged ascending close lists per symbol, strictly before `before_date`.

    dps_cache: {symbol: [{"date": "YYYY-MM-DD", "close": float, ...}]}
      (the positive-open scan's file - depth, possibly stale).
    records:   {as_of: {symbol: close}} (daily_closes.json - fresh tail;
      each as_of entry holds the closes the NEXT session opened from).
    """
    merged: dict[str, list[tuple[str, float]]] = {}

    for sym, rows in (dps_cache or {}).items():
        for row in rows:
            d = str(row.get("date", ""))
            close = row.get("close")
            if d and close and d < before_date:
                merged.setdefault(sym, []).append((d, float(close)))

    for as_of, closes in (records or {}).items():
        if as_of >= before_date:
            continue
        for sym, close in closes.items():
            merged.setdefault(sym, []).append((as_of, float(close)))

    out: dict[str, list[float]] = {}
    for sym, points in merged.items():
        seen: set[str] = set()
        ordered: list[float] = []
        for d, close in sorted(points):
            if d in seen:
                continue
            seen.add(d)
            ordered.append(close)
        if ordered:
            out[sym] = ordered
    return out


# --- Context object the engine consumes ------------------------------------


@dataclass
class MarketContext:
    """
    Market-level evidence for the decision engine. All fields optional;
    None/empty = unknown = the corresponding gate passes.
    """

    # Rule 11 - index trend.
    index_below_sma: bool | None = None
    index_last_close: float | None = None
    index_sma: float | None = None
    index_window: int = 20

    # Rule 11 data-quality veto. A history that does not reach the last
    # completed session means the gate is blind, not healthy: stale=True
    # vetoes entries (loudly) instead of passing on absent evidence.
    index_history_stale: bool = False
    index_history_newest: str | None = None
    index_history_expected: str | None = None

    # Rule 12 - foreign flow.
    foreign_flow_blocked: bool | None = None
    foreign_flow_streak: int | None = None
    foreign_flow_sum_usd: float | None = None
    # v0.10.0 - the full investor-type read (who is pumping / dumping).
    inst_foreign_net_usd: float | None = None
    inst_retail_net_usd: float | None = None
    inst_institutional_net_usd: float | None = None
    inst_retail_fomo: bool = False
    inst_smart_retail_war: bool = False
    # v0.16.2 Rule 12c - the pump/dump leaders by name and net.
    inst_top_buyer: dict | None = None
    inst_top_seller: dict | None = None

    # Rule 13 - multi-day extension (per-symbol closes).
    daily_closes: dict[str, list[float]] = field(default_factory=dict)

    # v2.1.0 Rule 11c - the live session tape. The KSE-100's live
    # day-change, captured on the same page as every snapshot and
    # injected by the decide cycle. None = unavailable: the gate
    # degrades to pass, exactly like every other live-only input.
    index_change_pct: float | None = None
    index_quote_status: str | None = None


def apply_index_proxy(ctx: MarketContext, vw_change_pct) -> None:
    """
    Feed Rule 11c from the tape's own money lens (replay/backtest path).

    Stored snapshots predate the index-quote capture, so the historical
    stand-in for the KSE-100's live direction is the value-weighted
    change of the OPEN cross-section at the decision timestamp
    (market_vw_change_pct - computed from that snapshot only, no
    look-ahead). Live trading uses the real page quote instead; this
    proxy is clearly badged PROXY in the context so any surfaced
    metadata never mistakes one for the other.

    A NaN/None/absent value leaves the context untouched - the gate
    degrades to pass, the same contract as the live side.
    """
    try:
        import math as _math

        if isinstance(vw_change_pct, (int, float)) and _math.isfinite(
            float(vw_change_pct)
        ):
            ctx.index_change_pct = float(vw_change_pct)
            ctx.index_quote_status = "PROXY"
    except (TypeError, ValueError):
        pass


def load_context(config: dict | None = None, as_of: str | None = None) -> MarketContext:
    """
    Build the MarketContext from data files. Every read failure degrades
    to unknown - the loader can never break a trading cycle.

    as_of ("YYYY-MM-DD"): walk-forward mode for the replay harness -
    every history is truncated to sessions STRICTLY BEFORE that date,
    and index staleness is judged against the last session completed
    before it, so a replay never reads evidence its decision time had
    not produced yet. Live callers omit it (today's files, today's
    gates).
    """
    config = config or {}
    ctx = MarketContext(
        index_window=int(config.get("index_sma_window", 20)),
    )

    # Index trend - and the staleness of the file it reads. 2026-09-10:
    # the history was fetched five hours after the morning's entries, so
    # Rule 11 passed all morning on absent evidence without knowing it.
    # A stale file now rides along in the context as an explicit veto
    # input instead of silently degrading the gate to "pass".
    try:
        from fetch_index_history import (
            load_history,
            newest_completed_session_date,
        )
        rows = load_history() or []
        if as_of:
            rows = [r for r in rows if r["date"].isoformat() < as_of]
        newest = max((r["date"] for r in rows if r.get("date")), default=None)
        try:
            from datetime import date as _date
            from datetime import datetime, timezone

            from psx_core import sessions as _sessions

            anchor = (
                _date.fromisoformat(as_of)
                if as_of
                else _sessions.trading_date(
                    datetime.now(timezone.utc)
                )
            )
            expected = newest_completed_session_date(anchor)
        except Exception:  # noqa: BLE001
            expected = None
        ctx.index_history_newest = (
            newest.isoformat() if newest else None
        )
        ctx.index_history_expected = (
            expected.isoformat() if expected else None
        )
        ctx.index_history_stale = bool(
            newest is None or (expected is not None and newest < expected)
        )
        state = index_regime_state(rows, window=ctx.index_window)
        if state:
            ctx.index_below_sma = bool(state["below_sma"])
            ctx.index_last_close = state["last_close"]
            ctx.index_sma = state["sma"]
    except Exception:  # noqa: BLE001
        pass

    # Foreign flow history.
    try:
        ff_path = paths.DATA_DIR / "foreign_flow_history.jsonl"
        rows = []
        for line in ff_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        rows.sort(key=lambda r: str(r.get("date", "")))
        if as_of:
            rows = [r for r in rows if str(r.get("date", "")) < as_of]
        ff = foreign_flow_state(
            rows,
            streak_days=int(config.get("foreign_flow_streak_days", 3)),
            min_net_usd=float(config.get("foreign_flow_min_net_usd", -5e6)),
        )
        ctx.foreign_flow_blocked = bool(ff["blocked"])
        ctx.foreign_flow_streak = ff["streak"]
        ctx.foreign_flow_sum_usd = ff["sum_usd"]
        inst = institutional_state(
            rows,
            fomo_ratio=float(config.get("institutional_fomo_ratio", 1.35)),
            min_net_usd=float(
                config.get("institutional_fomo_min_net_usd", 2e6)
            ),
            war_min_side_usd=float(
                config.get("institutional_war_min_side_usd", 1e7)
            ),
            war_min_retail_usd=float(
                config.get("institutional_war_min_retail_usd", 1e6)
            ),
        )
        ctx.inst_foreign_net_usd = inst["foreign_net_usd"]
        ctx.inst_retail_net_usd = inst["retail_net_usd"]
        ctx.inst_institutional_net_usd = inst["institutional_net_usd"]
        ctx.inst_retail_fomo = bool(inst["retail_fomo"])
        ctx.inst_smart_retail_war = bool(inst["smart_retail_war"])
        ctx.inst_top_buyer = inst.get("top_buyer")
        ctx.inst_top_seller = inst.get("top_seller")
    except Exception:  # noqa: BLE001
        pass

    # Daily closes (extension gate).
    try:
        dps_cache = None
        cache_path = paths.PROCESSED_DIR / "psx_eod_history.json"
        if cache_path.exists():
            dps_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        dps_cache = None
    try:
        from daily_closes import load_records
        records = load_records()
    except Exception:  # noqa: BLE001
        records = {}

    try:
        today = as_of
        if not today:
            from datetime import datetime, timezone

            from psx_core import sessions as _sessions
            today = _sessions.trading_date(
                datetime.now(timezone.utc)
            ).isoformat()
    except Exception:  # noqa: BLE001
        today = "9999-12-31"

    try:
        ctx.daily_closes = merge_daily_closes(dps_cache, records, today)
    except Exception:  # noqa: BLE001
        ctx.daily_closes = {}

    return ctx
