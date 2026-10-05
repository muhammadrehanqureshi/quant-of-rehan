"""
Sentinel-EOD runner - three modes driven by the workflow clock:

  reference  (~14:25 PKT)  store prices to measure the last-hour surge
  pick       (~15:28 PKT)  score the cross-section, publish the Top-5,
                           open the tracker, update volume baselines
  trace      (morning)     watch each open pick: +2% win / -2% stop /
                           force-close at 11:30 PKT; email outcomes

Every real run stamps data/heartbeat.json. Signals go to the repo's
signals issue (the owner's email) and SIGNALS.md. All state is JSON
committed by the workflow after each run - the machine is stateless.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eod_bot as eod_bot  # noqa: E402
from eod_bot import (  # noqa: E402
    FORCE_CLOSE_MIN_UTC,
    append_ledger,
    apply_weight_overrides,
    ledger_summary,
    load_json,
    pick_top,
    save_json,
    set_live_weights,
    store_window_open,
    trace_pick,
)

# v2.6.0 STRATEGY SWITCH (owner's order, 2026-09-30): the pick path
# runs the MORNING-FADE engine by default (buy late momentum, sell in
# the first minutes of the next session). The old lock-continuation
# policy stays available behind morning_fade.STRATEGY_SWITCH = false.
try:  # pragma: no cover - import guard mirrors every other layer
    import morning_fade
    from morning_fade import (  # noqa: F401
        exit_plan as _mf_exit_plan,
        rank_and_pick as _mf_rank_and_pick,
        score_rows as _mf_score_rows,
    )
    from overnight_memory import overnight_pairs_from_sessions  # noqa: F401
    MORNING_FADE_ENABLED = bool(morning_fade.STRATEGY_SWITCH)
except Exception as _mf_exc:  # noqa: BLE001 - the switch must never kill the runner
    print(f"pick: morning-fade engine unavailable ({_mf_exc}) - legacy policy active")
    MORNING_FADE_ENABLED = False
from psx_core import paths, sessions, universe as universe_mod  # noqa: E402
from psx_core import feed  # noqa: E402


def poll_kse100_quotes() -> dict:
    """One feed poll projected to the KMIALL universe (production path:
    fetch_snapshot -> build_universe_snapshot, with retries)."""
    import argparse
    import time

    symbols = universe_mod.load()
    http = requests.Session()
    http.headers.update({"User-Agent": "Mozilla/5.0 (sentinel-eod)"})
    args = argparse.Namespace(
        market="REG", timeout=30.0, min_instruments=feed.MIN_EXPECTED_INSTRUMENTS
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            market_data = feed.fetch_snapshot(
                http, market=args.market, timeout=args.timeout,
                min_instruments=args.min_instruments,
            )
            snap = feed.build_universe_snapshot(market_data, symbols, args.market)
            if snap.get("quotes"):
                return snap
            last_error = feed.FeedError("universe projection produced 0 quotes")
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_error = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"feed poll failed after retries: {last_error}")

REPO_ROOT = Path(__file__).resolve().parents[1]
PICKS_DIR = REPO_ROOT / "data" / "picks"
TRACKER = REPO_ROOT / "data" / "tracker.json"
LEDGER = REPO_ROOT / "data" / "ledger.jsonl"
REFIT = REPO_ROOT / "data" / "refit.json"
BASELINES = REPO_ROOT / "data" / "volume_baseline.json"
REFERENCE = REPO_ROOT / "data" / "reference_prices.json"
HEARTBEAT = REPO_ROOT / "data" / "heartbeat.json"
SIGNALS_MD = REPO_ROOT / "SIGNALS.md"
NOTIFIED = REPO_ROOT / "data" / "notified.json"
CLOSE_HISTORY = REPO_ROOT / "data" / "close_history.json"

# The seatbelt's Guard B watches this file in the repo to decide when
# the morning trace needs rescue - it must be committed, not ignored.
HEARTBEAT_TRACKED = True

OWNER_REPO = "muhammadrehanqureshi/sentinel-eod"
ISSUE_TITLE = "📣 Sentinel-EOD - evening picks & morning outcomes"

PKT = ZoneInfo("Asia/Karachi")

# Red-tape bar (v2.2.0): when the market itself is bleeding, a candidate
# must prove more liveness to earn the pick - a surge on a hostile tape
# has to survive the night against the whole market's gravity. Data-
# weighted selectivity: the bar rises, nothing is banned.
RED_TAPE_KSE100_PCT = -0.5
RED_TAPE_MIN_LATE_PCT = 0.3

# v2.3.0 the LOCK POLICY (refined corpus law, 2026-09-21). The policy
# backtest over the same 30 sessions that produced the >=8% law shows
# one-pick-per-day at rank-1 lands only 57.1% (net -0.04%) - while the
# refined selection inside that class lands 74.1% (net +0.57%, total
# +15.3%). The measured refinements, each earning its place:
#   * LOCKED closes only (>=9.9%): 52.7% vs 36.7% for 8.0-9.9 - the
#     lock seal is the edge; "almost locked" is not;
#   * >=Rs 500M traded value vetoed: 15.4% win (n=13) - the crowd
#     already got in, that volume is distribution;
#   * 5-8% open-gap vetoed (backtest-only feature; live feed carries
#     no open price - enforced in the backtest, skipped live);
#   * rank by lock history: 2nd lock day wins 73.3%, green-streak >=3
#     wins 67.5%, first lock 47.4% - the bonus curve below encodes it.
LOCK_CLASS_PCT = 9.9          # locked at the 10% circuit means >=9.9
DISTRIBUTION_VALUE_PKR = 500_000_000
LOCK_RANK_BONUS = 0.15        # weight units; scorer weights are 0.10-0.30

# v2.2.4 (owner's order, 2026-09-19): every card says only "next market
# day" - never "tomorrow" (a Friday's tomorrow is a closed Saturday)
# and never a concrete weekday name (the bot cannot know PSX public
# holidays). The old day-name helpers are gone with their callers.


def pick_window_minutes(weekday: int) -> tuple[int, int]:
    """The DECISION window in PKT minutes (owner's spec v2.2.1, 2026-09-18):

    Mon-Thu: analysis 15:00-15:23, card delivered by 15:25 SHARP,
    the owner places his order at 15:29. Friday: everything +1h
    (card by 16:25, order at 16:29). NOTHING may decide after the
    window closes - a pick the owner cannot act on is noise, not a
    signal. Rescues (watchdogs :26/:28, emergency tier :26-:28) all
    fit INSIDE the window so even a rescued pick is still usable.
    """
    if weekday == 4:  # Friday
        return 16 * 60, 16 * 60 + 28
    return 15 * 60, 15 * 60 + 28


def now_pkt() -> datetime:
    return datetime.now(PKT)


def stamp_heartbeat(source: str) -> None:
    save_json(HEARTBEAT, {
        "utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
    })


# --- Close history (the streak memory + multi-session indicators) --------
def update_close_history(quotes: dict, today: str) -> dict:
    """Store each symbol's session record per day (latest 10 kept).

    v2.1.5: full records - chg %, close, high, low, volume - because
    the scorer's multi-session indicators (multi-day momentum, 10-day
    breakout, day-range sufficiency) read more than the bare change.
    Idempotent per day (rescue runs never duplicate).
    """
    hist = load_json(CLOSE_HISTORY, {"sessions": {}})
    sessions = hist.setdefault("sessions", {})
    if today in sessions:
        return hist  # already stored today (rescue run) - idempotent
    day: dict[str, dict] = {}
    for sym, q in quotes.items():
        q = q or {}
        frac = q.get("changePercent")
        price = q.get("price")
        if not isinstance(frac, (int, float)) or not price:
            continue
        day[sym] = {
            "chg": round(frac * 100.0, 3),
            "c": price,
            "h": q.get("high"),
            "l": q.get("low"),
            "vol": q.get("volume"),
            "value": q.get("value"),
        }
    sessions[today] = day
    # keep the last 10 sessions only
    for old in sorted(sessions.keys())[:-10]:
        sessions.pop(old, None)
    save_json(CLOSE_HISTORY, hist)
    return hist


def session_history_map(hist: dict, today: str) -> dict[str, list[dict]]:
    """Per-symbol prior session records for the whole cross-section
    (newest last, today excluded, last 5 sessions)."""
    sessions = (hist or {}).get("sessions", {})
    prior_dates = [d for d in sorted(sessions.keys()) if d < today]
    if not prior_dates:
        return {}
    out: dict[str, list[dict]] = {}
    for d in prior_dates[-5:]:
        for sym, rec in sessions[d].items():
            out.setdefault(sym, []).append(rec)
    return out


# --- Volume baselines (self-bootstrapping EMA, 20-session memory) --------
def update_baselines(quotes: dict) -> dict:
    """Fold today's volume into the 20-session EMA baselines.

    Order-of-operations contract (v2.1.0): scoring uses the OLD
    baselines; this EMA update runs AFTER the pick is published. The
    old order let today's surge inflate its own denominator (a 3x day
    scored as ~1.14x), silencing exactly the signal this bot buys.
    """
    baselines = load_json(BASELINES, {})
    alpha = 1.0 / 20.0
    for sym, q in quotes.items():
        vol = q.get("volume")
        if not vol or vol <= 0:
            continue
        rec = baselines.get(sym) or {"avg_volume_20": None, "sessions": 0}
        prev = rec.get("avg_volume_20")
        rec["avg_volume_20"] = (
            vol if prev is None else prev + alpha * (vol - prev)
        )
        rec["sessions"] = rec.get("sessions", 0) + 1
        rec["updated"] = datetime.now(timezone.utc).isoformat()[:10]
        baselines[sym] = rec
    save_json(BASELINES, baselines)
    return baselines


def build_cross_section(
    snapshot: dict,
    reference: dict,
    baselines: dict,
    sector_flow: dict | None = None,
    session_history: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Flatten the feed snapshot into scorer rows."""
    sym_sector = (sector_flow or {}).get("symbolToSector") or {}
    sec_share = (sector_flow or {}).get("sectorShare") or {}
    rows = []
    for sym, q in (snapshot.get("quotes") or {}).items():
        if not q or not q.get("price"):
            continue
        frac = q.get("changePercent")
        ref_price = (reference or {}).get(sym)
        # STALE-REFERENCE GUARD (v2.1.0): the reference is only valid for
        # today's session. Yesterday's file must never leak into today's
        # late-momentum feature (the 2026-09-17 bug that hid surges).
        late = None
        if (
            ref_price
            and q["price"]
            and (reference or {}).get("_date") == snapshot.get("_date")
        ):
            late = (q["price"] / ref_price - 1.0) * 100.0
        sector = sym_sector.get(sym)
        rows.append({
            "symbol": sym,
            "price": q.get("price"),
            "high": q.get("high"),
            "low": q.get("low"),
            "volume": q.get("volume"),
            "value": q.get("value"),
            "change_pct": (
                frac * 100.0 if isinstance(frac, (int, float)) else None
            ),
            # Last-hour drift from today's reference run (None until it
            # has stored prices today; the dead-stock gate refuses
            # candidates without it).
            "late_momentum_pct": late,
            "avg_volume_20": (baselines.get(sym) or {}).get("avg_volume_20"),
            # YESTERDAY's traded value (v2.3.3): the prior-day
            # participation floor reads it - a lock on a dead prior day
            # has no follow-through behind it (grind 8 refinement A).
            "prev_day_value": (
                ((session_history or {}).get(sym) or [{}])[-1].get("value")
                if (session_history or {}).get(sym) else None
            ),
            # Sector's share of the day's traded value (0..1), only for
            # sectors above the market-average activity bar.
            "sector_flow_score": (
                sec_share.get(sector) if sector else None
            ),
            # Prior session records (v2.1.5): feeds the multi-day
            # momentum, 10-day breakout, and range-sufficiency features.
            "session_history": (session_history or {}).get(sym),
            # The raw quote (v2.1.6): feeds the order-book features
            # (book pressure, aggression). pick_top extracts only the
            # computed scores into the published cards.
            "quote": q,
        })
    return rows


def compute_sector_flow(snapshot: dict) -> dict:
    """Each sector's share of the day's traded value, v2.1.0.

    Returns {'symbolToSector': ..., 'sectorShare': {sector: share_0_1}}.
    Only sectors trading above the market-average share get a nonzero
    score (half their relative dominance, capped at 1) - the feature
    should reward HOT sectors, not merely existing ones.
    """
    sector_map_path = REPO_ROOT / "data" / "sector_map.json"
    raw = load_json(sector_map_path, {})
    sym_sector = raw.get("symbolToSector") or {}
    if not sym_sector:
        return {"symbolToSector": {}, "sectorShare": {}}

    sec_value: dict[str, float] = {}
    for sym, q in (snapshot.get("quotes") or {}).items():
        sector = sym_sector.get(sym)
        if not sector:
            continue
        val = (q or {}).get("value") or 0.0
        if val > 0:
            sec_value[sector] = sec_value.get(sector, 0.0) + val

    total = sum(sec_value.values())
    if total <= 0:
        return {"symbolToSector": sym_sector, "sectorShare": {}}

    n_active = len(sec_value)
    avg_share = 1.0 / n_active if n_active else 0.0
    share: dict[str, float] = {}
    for sector, val in sec_value.items():
        s = val / total
        if s > avg_share:  # hotter than an average sector
            share[sector] = min(1.0, 0.5 * s / avg_share if avg_share else 0.0)
    return {"symbolToSector": sym_sector, "sectorShare": share}


# --- Email delivery (signals issue -> owner's inbox) ----------------------
def _api(url: str, token: str, payload: dict | None = None, method: str = "GET"):
    resp = requests.request(
        method, url,
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json"},
        json=payload, timeout=30,
    )
    return resp


def ensure_issue(token: str) -> int | None:
    data = _api(
        f"https://api.github.com/repos/{OWNER_REPO}/issues?state=all&per_page=50",
        token,
    ).json()
    for issue in data if isinstance(data, list) else []:
        if issue.get("title") == ISSUE_TITLE:
            return issue["number"]
    resp = _api(
        f"https://api.github.com/repos/{OWNER_REPO}/issues",
        token,
        {"title": ISSUE_TITLE,
         "body": "Evening picks and next-morning outcomes post here."},
        "POST",
    )
    return resp.json().get("number") if resp.ok else None


def post_event(token: str, issue_no: int, body: str) -> bool:
    resp = _api(
        f"https://api.github.com/repos/{OWNER_REPO}/issues/{issue_no}/comments",
        token, {"body": body}, "POST",
    )
    return resp.ok


def load_notified() -> dict:
    return load_json(NOTIFIED, {"posted": []})


def save_notified(state: dict) -> None:
    save_json(NOTIFIED, state)


# --- SIGNALS.md -----------------------------------------------------------
def render_evening_md(
    picks: list[dict], picks_date: str, market_regime: float | None = None
) -> str:
    lines = [
        f"# Sentinel-EOD - evening picks for {picks_date}",
        "",
        "Buy at/near the close. Next session: sell at **+2.0%**,",
        "hard stop **-1.0%**, force-close 11:30 PKT if neither hits.",
        "",
    ]
    if market_regime is not None:
        bar = " (red-tape bar: late momentum ≥ +0.3% enforced)" \
            if market_regime <= RED_TAPE_KSE100_PCT else ""
        lines.insert(2, f"Market at analysis: **KSE-100 {market_regime:+.2f}%**{bar}")
        lines.insert(3, "")
    if any(p.get("degraded") for p in picks):
        lines.insert(
            2,
            "⚠ **DEGRADED MODE** - the 14:20 reference capture was lost, so "
            "the final-hour feature is substituted by the day-change shape. "
            "Evidence is weaker than usual; treat sizes accordingly.",
        )
        lines.insert(3, "")
    if not picks:
        lines += [
            f"**⭕ NO LIVE CANDIDATE - NO BUYING FOR THE NEXT MARKET DAY**",
            "",
            "Every name on the board failed the data test (dead final-hour",
            "tape, streak exhaustion, no volume). This card IS today's signal -",
            "the bot ran, the data spoke, and it said stand aside.",
            "",
            "_A signal that was withheld by the data is not a dropped signal._",
        ]
        return "\n".join(lines) + "\n"
    lines += [
        "| # | Symbol | Entry* | Score | Last hr % | Close pos | Vol surge | Book B/A | Tape | Streak | Breakout |",
        "|---|--------|--------|-------|-----------|-----------|-----------|----------|------|--------|----------|",
    ]
    for i, p in enumerate(picks, 1):
        flag = " ⚠" if p.get("streak_flag") else ""
        bp = p.get("book_pressure")
        bp_txt = f"{bp:.2f}" if bp is not None else "-"
        ag = p.get("aggression")
        ag_txt = f"{ag:.2f}" if ag is not None else "-"
        md = p.get("multi_day")
        md_txt = f"{md:.2f}" if md is not None else "-"
        brk = p.get("breakout")
        brk_txt = "NEW-HIGH" if brk == 1.0 else (f"{brk:.2f}" if brk is not None else "-")
        lm = p.get("late_momentum_pct")
        lm_txt = f"{lm:.2f}" if lm is not None else "-"
        cp = p.get("close_position")
        cp_txt = f"{cp:.2f}" if cp is not None else "-"
        vs = p.get("volume_surge")
        vs_txt = f"{vs:.2f}" if vs is not None else "-"
        lines.append(
            f"| {i} | **{p['symbol']}{flag}** | {p['entry_price']:.2f} | "
            f"{p['score']:.3f} | "
            f"{lm_txt} | "
            f"{cp_txt} | "
            f"{vs_txt} | "
            f"{bp_txt} | {ag_txt} | {md_txt} | {brk_txt} |"
        )
    lines += [
        "",
        "*Entry = analysis-time price (window 15:00-15:23 / 16:00-16:23).",
        "Signal by 15:25/16:25 - place your order at 15:29/16:29.",
        "Book B/A: 0.5 balanced, >0.5 bid wall (buyers stacking), <0.5 ask wall",
        "(sellers stacking). Tape: 0 calm block prints (quiet accumulator),",
        "1 frantic small prints (bulls chasing). Streak: multi-day run score.",
    ]
    for p in picks:
        if p.get("streak_flag"):
            lines += ["", f"{p['symbol']}: {p['streak_flag']}"]
        if p.get("lock_memory_flag"):
            lines += ["", f"{p['symbol']}: {p['lock_memory_flag']}"]
    lines += ["", f"_Paper ledger - every outcome tracked net of costs._"]
    refit = load_json(REPO_ROOT / "data" / "refit.json", {})
    if refit:
        lines.append(
            f"Learning: weights re-fit on {refit.get('generated', '?')[:10]} "
            f"({refit.get('trades', 0)} trades, "
            f"{refit.get('features_moved', 0)} features moved) - the "
            f"scorer keeps adjusting to what the tape actually pays."
        )
    return "\n".join(lines) + "\n"


def render_morning_md(summary: dict, outcomes: list[dict], open_n: int) -> str:
    lines = [
        "# Sentinel-EOD - morning trace",
        "",
        f"Ledger: {summary.get('trades', 0)} closed | "
        f"{summary.get('win_rate_pct', 0)}% wins | "
        f"avg net {summary.get('avg_net_pct', 0)}% | "
        f"sum net {summary.get('sum_net_pct', 0)}%",
    ]
    refit = load_json(REPO_ROOT / "data" / "refit.json", {})
    if refit:
        lines.append(
            f"Learning: scorer re-fit {refit.get('generated', '?')[:10]} "
            f"({refit.get('features_moved', 0)} features moved)."
        )
    lines += [""]
    if outcomes:
        lines.append("| Symbol | Entry | Exit | Outcome | Net % |")
        lines.append("|--------|-------|------|---------|-------|")
        for o in outcomes:
            lines.append(
                f"| {o['symbol']} | {o['entry_price']:.2f} | "
                f"{o['exit_price']:.2f} | {o['outcome']} | "
                f"{o['net_return_pct']:+.2f}% |"
            )
    else:
        lines.append("_No exits this pass - picks still inside the band._")
    lines.append("", )
    lines.append(f"_Open picks being traced: {open_n}_")
    return "\n".join(lines) + "\n"


# --- Modes -----------------------------------------------------------------
def mode_reference(token: str | None) -> int:
    # v2.2.4 holiday guard: no session, no reference worth storing.
    from psx_core.sessions import is_holiday
    if is_holiday(now_pkt().date()):
        print("reference: official PSX holiday - standing down.")
        return 0
    # v2.2.3 idempotent: the 14:40 self-heal slot re-fires the same mode.
    # It must never SHORTEN a good 14:20 capture (the drift window the
    # late-momentum feature measures). Recapture only when today's
    # reference is missing or suspiciously thin (partial feed failure).
    existing = load_json(REFERENCE, None) or {}
    today = now_pkt().date().isoformat()
    if existing.get("_date") == today and len(existing) >= 51:
        print(
            f"reference: today's capture already stored ({len(existing) - 1} "
            "prices) - keeping it (idempotent self-heal)"
        )
        stamp_heartbeat("reference")
        return 0
    snapshot = poll_kse100_quotes()
    prices = {
        "_date": now_pkt().date().isoformat(),  # staleness guard key
        **{
            sym: q.get("price")
            for sym, q in (snapshot.get("quotes") or {}).items()
            if q and q.get("price")
        },
    }
    save_json(REFERENCE, prices)
    stamp_heartbeat("reference")
    print(f"reference: stored {len(prices) - 1} prices at {now_pkt():%H:%M} PKT")
    return 0


def kse100_change_pct(snapshot: dict) -> float | None:
    """The KSE-100's live day-change. v2.2.5: the feed itself carries
    the real index quote (psx_core.broker_feed.parse_exs_message since
    v4.0.0) - prefer it; the value-weighted cross-section remains the
    fallback for a snapshot where the index block is missing. None when
    neither source is available."""
    idx = snapshot.get("index") or {}
    frac = idx.get("changePercent")
    if isinstance(frac, (int, float)):
        return float(frac)
    num = den = 0.0
    for q in (snapshot.get("quotes") or {}).values():
        val = (q or {}).get("value") or 0.0
        frac = (q or {}).get("changePercent")
        if val > 0 and isinstance(frac, (int, float)):
            num += val * frac
            den += val
    return (num / den) * 100.0 if den > 0 else None


def apply_blowoff_veto(picks: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Refuse SUB-8% picks closing AT the top of their day range (v2.2.7).

    Scope narrowed by the 30-day corpus (1052 simulated trades, 305
    symbols): the exhaustion signature (close at the extreme, no
    continuation) lives in the LOW-extension class - FABL 2026-09-16
    (+1.85%, close_position 1.00, force-closed). The >=8% momentum
    class CONTINUES overnight regardless of close position (49.3%
    forward win, n=140) - a close at the high there is the lock, not
    exhaustion. Missing close_position passes (never invent a veto).
    """
    kept, blocked = [], []
    for p in picks:
        cp = p.get("close_position")
        chg = p.get("change_pct")
        strong = chg is not None and float(chg) >= 8.0
        if cp is not None and not strong and float(cp) >= 0.98:
            blocked.append(
                (
                    p["symbol"],
                    f"blow-off close: position {float(cp):.2f} of day range "
                    "on a sub-8% day - exhaustion, not strength "
                    "(FABL 2026-09-16 type)",
                )
            )
        else:
            kept.append(p)
    return kept, blocked


def apply_momentum_gate(picks: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Keep only LOCKED-at-close candidates (v2.3.0, refined corpus law).

    Two layers, both earned on the 30-session corpus under the owner's
    universal law (TP 2 / SL -1, real cost stack):

    Layer 1 (v2.2.7): the overnight-continuation gradient in day
    extension is strictly monotonic - <2% wins 7.9%, 2-4% 13.3%,
    4-6% 17.5%, 6-8% 33.3%, >=8% 49.3% (n=140).

    Layer 2 (v2.3.0): the policy backtest split the class further.
    LOCKED closes (>=9.9%) win 52.7% while 8.0-9.9% "almost locked"
    win only 36.7% - and candidates trading >=Rs 500M on the lock day
    win 15.4% (n=13): that is the crowd already aboard, distribution
    not accumulation. A day with no qualifying candidate produces a
    no-pick card - refusing to bet is the strategy working. Missing
    day-change is disqualified (the gate requires evidence).
    """
    kept, blocked = [], []
    for p in picks:
        chg = p.get("change_pct")
        if chg is None:
            blocked.append(
                (p["symbol"], "day-change missing - no extension evidence "
                 "(corpus law requires it)")
            )
            continue
        chg = float(chg)
        if chg < LOCK_CLASS_PCT:
            blocked.append(
                (p["symbol"],
                 f"extension {format(chg, '+.2f')}% below the locked "
                 f"close line (+{LOCK_CLASS_PCT}% - corpus 2026-09-21: "
                 "locked 52.7% vs almost-locked 36.7%)")
            )
            continue
        value = p.get("value")
        if value is not None and float(value) >= DISTRIBUTION_VALUE_PKR:
            blocked.append(
                (p["symbol"],
                 f"traded value Rs {float(value)/1e6:,.0f}M on the lock - "
                 "the >=500M distribution trap (15.4% forward win, n=13)")
            )
            continue
        kept.append(p)
    return kept, blocked


def apply_lock_rank_bonus(
    picks: list[dict], close_history: dict[str, list[dict]] | None
) -> list[dict]:
    """Rank adjustment from the measured lock-history gradient (v2.3.1).

    Within the locked class the corpus says history decides: the 2nd
    consecutive lock day wins 73.3% (n=15), 3+ lock days 57.9%, the
    first lock day only 47.4%. The bonus encodes that curve in rank
    space (scorer weights run 0.10-0.30, so +0.15 for the 2-day lock
    is material but not dominating).

    v2.3.1: the separate green-streak bonus is GONE - the policy A/B
    (discovery Aug 6-Sep 4 vs validation Sep 7-17) showed it is
    collinear with lock_days (every re-lock is already green) and
    cost three picks on the full window. green_streak still travels
    on the card as evidence; only lock_days moves the rank.
    """
    sessions = (close_history or {})  # {sym: [ {chg, c, ...}, ... ] newest last}
    for p in picks:
        chg = p.get("change_pct")
        hist = sessions.get(p["symbol"]) or []
        # consecutive lock days INCLUDING today (today is the live row)
        lock_days = 1 if (chg is not None and float(chg) >= LOCK_CLASS_PCT) else 0
        for rec in reversed(hist):
            c = rec.get("chg")
            if c is not None and float(c) >= LOCK_CLASS_PCT:
                lock_days += 1
            else:
                break
        green_days = 0
        prev_c = chg
        for rec in reversed(hist):
            c = rec.get("chg")
            if c is not None and prev_c is not None and float(c) > 0 and float(prev_c) > 0:
                green_days += 1
                prev_c = c
            else:
                break
        p["lock_days"] = lock_days
        p["green_streak"] = green_days + (1 if (chg is not None and float(chg) > 0) else 0)
        bonus = 0.0
        if lock_days == 2:
            bonus += LOCK_RANK_BONUS
        elif lock_days >= 3:
            bonus += LOCK_RANK_BONUS / 2
        p["lock_bonus"] = round(bonus, 3)
    return picks


def _morning_fade_pick(
    rows: list[dict],
    mkt: float | None,
    sess_hist: dict[str, list[dict]],
    today: str,
    pkt: datetime,
    allow_degraded: bool = False,
    window_open_state: dict | None = None,
) -> list[dict]:
    """The morning-fade pick path (owner's order 2026-09-30).

    Bridges the runner's cross-section to morning_fade: overnight
    history per symbol from the close-history sessions, the 8-feature
    score, ONLY the 4 vetoes, rank-1-or-no-trade. Entry realism: the
    recorded entry price is the analysis read, and every card says the
    fill lands in the closing auction (15:24-15:30) - the owner orders
    at :29 inside the auction window, so the fill is the auction print,
    not the :23 quote (PSX close-price law, task 3).
    """
    import morning_fade as mf
    from overnight_memory import overnight_pairs_from_sessions

    hist = load_json(CLOSE_HISTORY, {"sessions": {}}) or {"sessions": {}}
    sessions = hist.get("sessions", {})

    enriched: list[dict] = []
    for r in rows:
        f = dict(r)
        # Per-symbol overnight pairs (closes to next closes/opens).
        f["overnight_pairs"] = overnight_pairs_from_sessions(sessions, r["symbol"])
        # Sector day-change for feature #7 (from the sector map shares;
        # the share score is remapped as a signed proxy: above-average
        # share of value = strength). Honest proxy, flagged on the card.
        sfs = r.get("sector_flow_score")
        f["sector_chg_pct"] = (sfs - 0.5) * 3.0 if sfs is not None else None
        # Previous close for the extension math (yesterday's close from
        # the stored sessions; never today's own).
        prior = (sess_hist.get(r["symbol"]) or [])
        f["prev_close"] = prior[-1].get("c") if prior else None
        # Late-window volume ratio: the :00 window-open read measures
        # the tape INSIDE the window; without it, the full-day surge
        # ratio stands in (flagged).
        wo = (window_open_state or {}).get("snapshots") or {}
        wo_row = wo.get(r["symbol"]) or {}
        if wo_row and r.get("volume"):
            base_vol = wo_row.get("volume")
            if base_vol:
                f["late_volume_ratio"] = (float(r["volume"]) - float(base_vol)) / max(1.0, float(base_vol)) * 1.0
        enriched.append(f)

    feats = mf.build_features(enriched, kse100_pct=mkt)
    scored = mf.score_rows(feats)
    pick, ranked, vetoed = mf.rank_and_pick(scored, kse100_pct=mkt)

    for sym, reason in vetoed:
        print(f"pick: VETO {sym} - {reason} (morning-fade)")
    print(
        f"pick: morning-fade ranked {len(ranked)} candidate(s), "
        f"vetoed {len(vetoed)}"
    )
    if not pick:
        print("pick: morning-fade - no candidate cleared the bar: NO TRADE")
        return []

    entry_price = pick["price"]
    plan = {
        "entry_realism": (
            "entry shown is the analysis read (~15:21-15:23 PKT); your "
            "fill is the closing-auction print (15:24-15:30) - order by "
            "15:29/16:29"
        ),
        "exit_ladder": mf.exit_plan.__doc__.split(chr(10))[0].strip(),
    }
    record = mf.signal_record(pick, today, pkt.isoformat())
    record.update(plan)
    pick_out = {
        "symbol": pick["symbol"],
        "score": pick["score_8f"],
        "raw_score": pick["score_8f"],
        "entry_price": entry_price,
        "change_pct": pick.get("change_pct"),
        "late_momentum_pct": pick.get("late_momentum_pct"),
        "close_position": pick.get("close_position"),
        "late_volume_ratio": pick.get("late_volume_ratio"),
        "extension_safety": pick.get("extension_safety"),
        "overnight_history": pick.get("overnight_history"),
        "book_strength": pick.get("book_strength"),
        "sector_context": pick.get("sector_context"),
        "range_sufficiency": pick.get("range_sufficiency"),
        "weight_coverage": pick.get("score_weight_coverage"),
        "score_components": pick.get("score_components"),
        "exit_plan": plan,
        "signal_log": record,
        "strategy": "morning-fade",
        "degraded": False,
    }
    print(
        f"pick: morning-fade PICK {pick_out['symbol']} "
        f"score {pick_out['score']:.3f} - sell at open+{mf.OPEN_SELL_MIN}min, "
        f"gap-stop {mf.GAP_STOP_PCT}%"
    )
    return [pick_out]


def mode_pick(token: str | None, window_open: bool = False) -> int:
    pkt = now_pkt()
    # v2.2.4 holiday guard: an official PSX holiday has no session -
    # the cron firing anyway must NOT open a book from stale quotes
    # or publish a "no candidate" card that reads like a decision.
    # (The seatbelt also stands down on holidays; this is the second
    # layer, in case anything dispatches manually.)
    from psx_core.sessions import is_holiday
    if is_holiday(pkt.date()):
        print(
            f"pick: {pkt.date()} is an official PSX holiday - no session, "
            "no book. Standing down."
        )
        return 0
    today = pkt.date().isoformat()
    if pkt.weekday() >= 5:
        print("pick: weekend - nothing to do")
        return 0
    # Owner's window contract (v2.2.2): 15:00-:23 is ANALYSIS time
    # (last-chance :23), the signal lands :25 SHARP, the owner orders
    # at :29. Friday is the same +1h.
    start, end = pick_window_minutes(pkt.weekday())
    if not (start <= pkt.hour * 60 + pkt.minute <= end):
        print(f"pick: outside the {start//60:02d}:{start%60:02d}-"
              f"{end//60:02d}:{end%60:02d} PKT window ({pkt:%H:%M}) - skip")
        return 0

    # v2.2.2 window-open read (the :00 cron): NO analysis, NO card -
    # just the raw cross-section of the tape at window-open, stored
    # for the :21 analysis read to measure in-window drift against.
    if window_open:
        snapshot = poll_kse100_quotes()
        store_window_open(snapshot, today, REPO_ROOT)
        stamp_heartbeat("pick")  # "the bot is alive" without a card
        print(f"pick: window-open tape stored ({len(snapshot.get('quotes') or {})} quotes)")
        return 0

    # v3.4.0 session cards: MARKET OPEN card on GitHub (primary) AND
    # Telegram (backup) once per market day - the bot announcing it is
    # running. Silent on holidays/weekends; kill-switch
    # session_cards_enabled. Never fatal.
    try:
        import session_cards

        _card_ok, _card_note = session_cards.announce_open()
        if _card_ok:
            print(f"session card: {_card_note}")
    except Exception as _card_exc:  # noqa: BLE001
        print(f"session card error (non-fatal): {_card_exc}")

    # v2.3.2: sync the per-symbol lock memory from the Sentinel repo
    # before scoring - best-effort, offline-safe (a failed refresh
    # leaves the committed copy; the pick never blocks on it).
    # v3.0.0: skipped - the clean engine does not read these stores.
    if eod_bot.MEMORY_LAYERS_ENABLED:
        try:
            from lock_memory import refresh_report
            tok = os.environ.get("GITHUB_TOKEN", "")
            if refresh_report(token=tok or None):
                print("pick: per-symbol lock memory refreshed from the Sentinel")
        except Exception as _exc:  # noqa: BLE001
            print(f"pick: lock-memory refresh skipped ({_exc})")

        # v2.4.0: sync the rolling market lessons (what the tape taught
        # every session) from the Sentinel repo - same offline-safe rule.
        try:
            from market_lessons import refresh_store
            tok = os.environ.get("GITHUB_TOKEN", "")
            if refresh_store(token=tok or None):
                print("pick: market lessons refreshed from the Sentinel")
        except Exception as _exc:  # noqa: BLE001
            print(f"pick: market-lessons refresh skipped ({_exc})")

    # One book per day: if a rescue run already published today's pick,
    # a late-arriving scheduled run must NOT overwrite it (the owner
    # may already be acting on the first book). BUT the delivery ledger
    # is checked first: if the book exists while a channel is still
    # unmarked, that channel failed earlier (the Sep-22 evening card
    # reached GitHub but Telegram silently failed) - retry ONLY the
    # missing channel(s) from the committed book, never re-decide.
    if (PICKS_DIR / f"{today}.json").exists():
        state = load_notified()
        key0 = f"pick:{today}"
        if key0 + ":gh" in state["posted"] and key0 + ":tg" in state["posted"]:
            print(f"pick: {today} already published and delivered - keeping "
                  "the first book (one pick per day)")
            return 0
        print(f"pick: {today} already published - retrying the missing "
              "delivery channel(s) only")
        payload0 = load_json(PICKS_DIR / f"{today}.json", None) or {}
        picks0 = payload0.get("picks") or []
        dirty = False
        if token and key0 + ":gh" not in state["posted"]:
            try:
                issue = ensure_issue(token)
                body0 = (
                    f"@muhammadrehanqureshi **SENTINELS OF REHAN Sentinel-EOD {today} "
                    f"(channel retry): "
                    + (f"{len(picks0)} pick(s) published" if picks0
                       else "NO LIVE CANDIDATE - NO BUYING FOR THE NEXT MARKET DAY")
                    + "**"
                )
                if issue and post_event(token, issue, body0):
                    state["posted"].append(key0 + ":gh")
                    dirty = True
            except Exception:  # noqa: BLE001 - email channel, never fatal
                print("pick: github retry unreachable (non-fatal)")
        if key0 + ":tg" not in state["posted"]:
            try:
                import telegram_notify
                if picks0:
                    ok = telegram_notify.send_pick(today, picks0, "")
                else:
                    ok = telegram_notify.send(
                        "⭕ <b>SENTINELS OF REHAN | Sentinel-EOD: NO LIVE CANDIDATE - NO BUYING "
                        "FOR THE NEXT MARKET DAY</b> - the bot ran and "
                        "decided: stand aside. This card is today's signal."
                    )
                if ok:
                    state["posted"].append(key0 + ":tg")
                    dirty = True
                    print("pick: telegram retry delivered")
                else:
                    print("pick: TELEGRAM RETRY FAILED - check the "
                          "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID secrets "
                          "and api.telegram.org reachability")
            except Exception as exc:  # noqa: BLE001 - backup, never fatal
                print(f"pick: telegram retry raised (non-fatal): {exc}")
        if dirty:
            save_notified(state)
        return 0

    snapshot = poll_kse100_quotes()
    baselines = load_json(BASELINES, None) or {}
    reference = load_json(REFERENCE, None) or {}
    snapshot["_date"] = today  # matches reference's _date guard

    # v2.2.4 corporate actions: fetch at the decision moment (book
    # closures / ex-dates / fresh results). Failure = layer inert.
    ca_map: dict = {}
    try:
        import corporate_actions
        ca_map = corporate_actions.fetch_corporate_actions()["bySymbol"]
        print(
            f"pick: corporate actions - {len(ca_map)} symbols with notices"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"pick: corporate actions fetch failed (inert): {exc}")

    sector_flow = compute_sector_flow(snapshot)
    hist = load_json(CLOSE_HISTORY, None) or {"sessions": {}}
    sess_hist = session_history_map(hist, today)
    rows = build_cross_section(
        snapshot, reference, baselines, sector_flow, sess_hist
    )
    # v2.2.0 SELF-LEARNING: if the weekly refit has learned weight
    # adjustments from the ledger, install them before scoring. The
    # book still opens from evidence, not opinion.
    # v3.0.0 owner simplification: the scorer uses its published base
    # weights - no ledger re-fits the book by itself. (Flip
    # eod_bot.MEMORY_LAYERS_ENABLED to True to re-arm.)
    if eod_bot.MEMORY_LAYERS_ENABLED:
        refit_state = load_json(REFIT, None)
        if refit_state:
            set_live_weights(apply_weight_overrides(refit_state))
            print(
                "pick: learned weights active "
                f"({refit_state.get('trades', '?')} trades studied)"
            )
    # v2.2.0 market regime: the bot measures the TAPE it is buying
    # into. On a red market, the liveness bar rises (data-weighted
    # selectivity - the surge must prove itself harder).
    mkt = kse100_change_pct(snapshot)
    min_late = RED_TAPE_MIN_LATE_PCT if (
        mkt is not None and mkt <= RED_TAPE_KSE100_PCT
    ) else None
    regime_note = (
        f"market {mkt:+.2f}% -> red-tape bar {RED_TAPE_MIN_LATE_PCT}%"
        if min_late else f"market {mkt:+.2f}%" if mkt is not None else "market: n/a"
    )
    print(f"pick: regime - {regime_note}")
    # v2.2.2 window persistence: the :00 read (if today's ran) lets the
    # pick measure each candidate's drift WITHIN the owner's window -
    # kept rising = confirmed, faded = demoted (never banned).
    window_open_state = load_json(REPO_ROOT / "data" / "window_open.json", None)
    if window_open_state and window_open_state.get("_date") != today:
        window_open_state = None  # a stale read must never feed today
    # v2.6.0 STRATEGY SWITCH: the morning-fade engine picks the book
    # by default (buy late momentum, sell first minutes). The legacy
    # lock-continuation policy (v2.3.0 corpus law: only locked >=9.9%
    # closes, lock-history rank bonus) stays intact behind the switch
    # for A/B comparison - flip morning_fade.STRATEGY_SWITCH to False.
    if MORNING_FADE_ENABLED:
        picks = _morning_fade_pick(
            rows, mkt, sess_hist, today, pkt,
            allow_degraded=reference.get("_date") != today,
            window_open_state=window_open_state,
        )
    else:
        # v2.3.0 the corpus law, refined: PSX overnight momentum lives in
        # the LOCKED-at-close class (+9.9%: 52.7% forward win vs 36.7% for
        # almost-locked) with the >=500M distribution trap vetoed (15.4%
        # forward win). The pool is widened BEFORE pick_top so locked
        # candidates survive the liveness gates, the lock-class gate
        # filters afterwards, and the measured lock-history bonus adjusts
        # the final rank. A day with no lock produces a no-pick card -
        # that is the strategy working.
        rows_wide = [
            r for r in rows
            if r.get("change_pct") is not None and float(r["change_pct"]) >= LOCK_CLASS_PCT
        ]
        pool = rows_wide + [r for r in rows if r not in rows_wide]
        picks = pick_top(
            pool, close_history=sess_hist, min_late=min_late,
            window_open=window_open_state,
            # v2.2.3: a dropped reference capture must never silently become
            # a false "no live candidate". When today's reference is absent,
            # the final hour is UNVERIFIABLE (instrument failure, not tape
            # verdict) - allow the day-change fallback so the owner still
            # gets a real, honestly-labeled decision.
            allow_degraded=reference.get("_date") != today,
        )
    if any(p.get("degraded") for p in picks):
        print("pick: DEGRADED MODE - reference capture missing, "
              "day-change shape substituted for the final hour")

    # v2.2.5 corporate-actions veto + evidence - the owner's DIVIDEND-
    # RUNWAY doctrine (supersedes the v2.2.4 blanket veto). Weeks before
    # the window, chasers accumulate = demand we RIDE; only the last
    # 3 trading sessions before the window/ex-date, the window, and the
    # ex-date are fatal - an EOD pick holds exactly one night, so a
    # 3-session runway guarantees the holding day clears the circus.
    # Missing data = no veto (degrades to pre-v2.2.4 behavior).
    if ca_map:
        import corporate_actions
        today_d = pkt.date()
        blocked = []
        for p in picks:
            reason = corporate_actions.book_closure_block(
                p["symbol"], today_d, actions=ca_map
            )
            if reason:
                blocked.append((p["symbol"], reason))
            else:
                p["fresh_results"] = corporate_actions.fresh_results(
                    p["symbol"], today_d, actions=ca_map
                )
                rw = corporate_actions.dividend_runway(
                    p["symbol"], today_d, actions=ca_map
                )
                if rw is not None:
                    p["dividend_runway"] = rw
        for sym, reason in blocked:
            print(f"pick: VETO {sym} - {reason}")
        if blocked:
            blocked_syms = {sym for sym, _ in blocked}
            picks = [p for p in picks if p["symbol"] not in blocked_syms]
            if not picks:
                print("pick: every candidate vetoed by book-closure windows")

    # v2.2.7/v2.3.0 the corpus law, refined: PSX overnight momentum
    # lives in the LOCKED-at-close class (+9.9%: 52.7% forward win vs
    # 36.7% for almost-locked) with the >=Rs 500M distribution trap
    # vetoed (15.4% forward win, n=13). A day with no lock produces a
    # no-pick card - that is the strategy working.
    before = len(picks)
    picks, ext_blocked = apply_momentum_gate(picks)
    for sym, reason in ext_blocked:
        print(f"pick: VETO {sym} - {reason}")
    print(
        f"pick: lock gate kept {len(picks)}/{before} "
        f"(locked closes >= {LOCK_CLASS_PCT}%, minus the 500M trap)"
    )
    # v2.3.0 lock-history rank bonus: 2nd lock day 73.3%, streak >=3
    # 67.5%, first lock 47.4% - the ranking follows the measurement.
    picks = apply_lock_rank_bonus(picks, sess_hist)
    # grind 8/9 lock-quality gates (full 175-session corpus): the
    # volume-ratio ceiling (>5x 20-day average = one-way distribution
    # into the circuit) and the prior-day participation floor (a dead
    # day before the lock has no follow-through behind it). Both halves
    # improved; missing evidence never gates.
    try:
        from lock_quality_gate import apply_lock_quality
        picks, lq_blocked = apply_lock_quality(picks)
        for sym, reason in lq_blocked:
            print(f"pick: VETO {sym} - {reason}")
        if lq_blocked:
            print(
                f"pick: lock-quality gate kept {len(picks)} "
                f"(volume ceiling 5x, prior-day floor Rs 0.5M)"
            )
    except Exception as exc:  # noqa: BLE001 - a gate module must never kill the pick
        print(f"pick: lock-quality gate skipped ({exc})")
    picks.sort(
        key=lambda p: (
            -(p["score"] + p.get("lock_bonus", 0.0)),
            -(p.get("change_pct") or 0.0),
        )
    )
    picks = picks[:1]

    # v2.2.7 blow-off veto, scoped by the same corpus: the exhaustion
    # signature (close at the day extreme, no continuation) lives in
    # the SUB-8% class. Inside the momentum class a close at the high
    # is the lock itself - never vetoed there.
    picks, cp_blocked = apply_blowoff_veto(picks)
    for sym, reason in cp_blocked:
        print(f"pick: VETO {sym} - {reason}")
    if cp_blocked and not picks:
        print("pick: every candidate vetoed - all picked at the day extreme")

    # Book-keeping AFTER scoring (today's data must never dilute its
    # own features): baselines fold, then close history stores - but
    # both fold EVERY session, pick or refused, so the 20-session EMA
    # and the streak memory never lose a gate-day.
    update_baselines(snapshot.get("quotes") or {})
    update_close_history(snapshot.get("quotes") or {}, today)

    if not picks:
        # The ALL-LIVE signal (v2.1.2): "no pick" is itself a data-driven
        # decision - publish it so silence is never ambiguous. The card
        # names the NEXT market day (owner's order: he must know the bot
        # ran and decided, not died).
        ref_missing = reference.get("_date") != today
        payload = {"pick_date": today, "picked_at_pkt": pkt.isoformat(),
                   "picks": [], "degraded": ref_missing,
                   "note": "no live candidate - no buying for the next market day"}
        save_json(PICKS_DIR / f"{today}.json", payload)
        SIGNALS_MD.write_text(
            render_evening_md([], today, mkt), encoding="utf-8"
        )
        stamp_heartbeat("pick")
        state = load_notified()
        key = f"pick:{today}"
        body = (f"@muhammadrehanqureshi **SENTINELS OF REHAN Sentinel-EOD {today}: ⭕ NO LIVE CANDIDATE "
                "- NO BUYING FOR THE NEXT MARKET DAY** - every name failed the data test "
                "tonight (dead final-hour tape, streak exhaustion, no volume). "
                "The bot ran and decided: stand aside.")
        if ref_missing:
            body += ("\n\n⚠ DEGRADED MODE: the 14:20 reference capture was lost "
                     "today, so candidates were screened on the day-change "
                     "shape instead of the final hour - and even that bar "
                     "found nothing worth buying.")
        dirty = False
        if token and key + ":gh" not in state["posted"]:
            try:
                issue = ensure_issue(token)
                if issue and post_event(token, issue, body):
                    state["posted"].append(key + ":gh")
                    dirty = True
            except Exception:  # noqa: BLE001
                print("pick: github email path unreachable (non-fatal)")
        if key + ":tg" not in state["posted"]:
            try:
                import telegram_notify
                if telegram_notify.send(
                    f"⭕ <b>SENTINELS OF REHAN | Sentinel-EOD: NO LIVE CANDIDATE - NO BUYING FOR "
                    f"THE NEXT MARKET DAY</b> - every name failed the data test "
                    "(dead tape / streak / liquidity). The bot ran and "
                    "decided: stand aside. This card is today's signal."
                ):
                    state["posted"].append(key + ":tg")
                    dirty = True
            except Exception as exc:  # noqa: BLE001 - never fatal, but LOUD
                print(f"pick: TELEGRAM CARD FAILED (non-fatal): {exc}")
        if dirty:
            save_notified(state)
        print("pick: NO LIVE CANDIDATE published as today's signal")
        return 0

    if not picks:
        print("pick: no scorable candidates today")
        return 0

    payload = {
        "pick_date": today,
        "picked_at_pkt": pkt.isoformat(),
        "analysis_window": "15:00-15:23" if pkt.weekday() != 4 else "16:00-16:23",
        "market_regime_pct": mkt,
        "red_tape_bar": min_late,
        "degraded": any(p.get("degraded") for p in picks),
        "picks": picks,
    }
    save_json(PICKS_DIR / f"{today}.json", payload)

    tracker = load_json(TRACKER, {"open": []})
    tracker["open"] = [
        {**p, "pick_date": today} for p in picks
    ]
    tracker["pick_date"] = today
    save_json(TRACKER, tracker)

    SIGNALS_MD.write_text(
        render_evening_md(picks, today, mkt), encoding="utf-8"
    )
    stamp_heartbeat("pick")

    # Delivery (v2.0.3): the two channels are FULLY INDEPENDENT - each
    # has its own dedup key and neither can block or silence the other.
    # GitHub's email path dying at 16:20 (API outage, token expired, a
    # dropped slot) must never take Telegram down with it: the owner's
    # standing order is "if GitHub fails, I still get it on Telegram".
    state = load_notified()
    key = f"pick:{today}"
    dirty = False

    body = (
        f"@muhammadrehanqureshi **Evening picks for {today}** - "
        "buy at/near the close (entry shown is analysis-time; your fill "
        "may differ slightly). Next market day: sell at +2.0%, stop -1.0%, "
        "force-close 11:30 PKT.\n\n"
        + "\n".join(
            f"**{i}. {p['symbol']}** - entry ~{p['entry_price']:.2f} "
            f"(score {p['score']:.3f})"
            + f"\n   Evidence: " + (
                f"day {p['late_momentum_pct']:+.2f}% (DEGRADED - final hour "
                "unverifiable, reference capture lost)"
                if p.get("degraded")
                else f"last-hr {p['late_momentum_pct']:+.2f}%"
            )
            + (
                f" | earnings: EPS {p['fresh_results']['eps']:+.2f} "
                f"({p['fresh_results'].get('growth_in_pat') or 0:+.1f}% PAT) "
                "- results catalyst live"
                if p.get("fresh_results")
                else ""
            )
            + (
                f" | dividend-runway {p['dividend_runway']} sessions "
                "(riding the chasers - dump before the window)"
                if p.get("dividend_runway") is not None
                else ""
            )
            + (f" | book {p['book_pressure']:.2f}" if p.get("book_pressure") is not None else "")
            + (f" | tape {p['aggression']:.2f}" if p.get("aggression") is not None else "")
            + (f" | streak {p['multi_day']:.2f}" if p.get("multi_day") is not None else "")
            + (f" | vpvr {p['vpvr']:.2f}" if p.get("vpvr") is not None else "")
            + (f" | breakout" if p.get("breakout") == 1.0 else "")
            + (
                f" | locks {p['lock_days']}x, green run {p['green_streak']}d"
                if p.get("lock_days") is not None else ""
            )
            + (f"\n   ⚠ {p['streak_flag']}" if p.get("streak_flag") else "")
            + (
                f"\n   {p['lock_memory_flag']}" if p.get("lock_memory_flag") else ""
            )
            for i, p in enumerate(picks, 1)
        )
    )

    # Channel 1: GitHub issue -> email. Needs the token; failures are
    # logged and NOT allowed to touch channel 2. The try/except is the
    # total-outage case: api.github.com unreachable must raise nothing
    # out of this block, or Telegram dies with it.
    if token and key + ":gh" not in state["posted"]:
        try:
            issue = ensure_issue(token)
            if issue and post_event(token, issue, body):
                state["posted"].append(key + ":gh")
                dirty = True
        except Exception:  # noqa: BLE001 - email channel, never fatal
            print("pick: github email path unreachable (non-fatal)")

    # Channel 2: Telegram. No token dependency, no GitHub dependency -
    # it fires even if channel 1 just crashed.
    if key + ":tg" not in state["posted"]:
        try:
            import telegram_notify

            if telegram_notify.send_pick(today, picks, mkt):
                state["posted"].append(key + ":tg")
                dirty = True
                print("pick: telegram delivered")
            else:
                print("pick: TELEGRAM DELIVERY FAILED - the backup "
                      "channel did not accept the card (secrets/network); "
                      "the watchdog slots will retry it")
        except Exception as exc:  # noqa: BLE001 - backup, never fatal
            print(f"pick: telegram raised (non-fatal): {exc}")

    if dirty:
        save_notified(state)
    print(f"pick: {len(picks)} picks published for {today}")
    return 0


def mode_trace(token: str | None) -> int:
    pkt = now_pkt()
    today = pkt.date().isoformat()
    if pkt.weekday() >= 5:
        print("trace: weekend")
        return 0

    # v2.2.7 holiday guard: a weekday holiday has no session - tracing
    # there would read Friday's stale highs/lows and could fabricate a
    # WIN/STOP from a tape that never traded. The pick simply waits;
    # the next real session resumes the trace (pick_date < today).
    from psx_core.sessions import is_holiday

    if is_holiday(pkt.date()):
        print(
            "trace: official PSX holiday - standing down "
            "(picks wait for the next session)."
        )
        return 0

    tracker = load_json(TRACKER, {"open": []})
    open_picks = [p for p in tracker.get("open", [])]
    if not open_picks:
        print("trace: no open picks")
        return 0
    # Only trace the day AFTER the pick date (and only that next session).
    pick_date = tracker.get("pick_date")
    if pick_date == today:
        print("trace: picks are for the NEXT session - nothing today")
        return 0
    if pick_date and pick_date > today:
        print("trace: pick date is in the future?! ignoring")
        return 0

    snapshot = poll_kse100_quotes()
    now_utc = datetime.now(timezone.utc)
    minutes = now_utc.hour * 60 + now_utc.minute

    # v2.6.0 session-opens memory: the FIRST morning print per symbol
    # is recorded (the closest honest proxy for the official open at
    # this poll cadence) - the morning-fade ladder and the overnight
    # features read it, and every card states the basis.
    from session_opens import record_session_open
    opens_state = load_json(REPO_ROOT / "data" / "session_opens.json", None) or {"sessions": {}}
    opens_state, opens_wrote = record_session_open(
        opens_state, today, snapshot.get("quotes") or {}
    )
    if opens_wrote:
        save_json(REPO_ROOT / "data" / "session_opens.json", opens_state)

    outcomes = []
    still_open = []
    for pick in open_picks:
        q = (snapshot.get("quotes") or {}).get(pick["symbol"]) or {}
        price = q.get("price")
        day_frac = q.get("changePercent")

        # Streak purge (v2.1.1): an open pick that upper-locks today is
        # in the FPJM-trap state - a frozen, one-sided tape where the
        # next day can gap straight into the stop with no exit. Sell
        # into the lock's buyer queue immediately (a lock has buyers;
        # it can be sold, just not bought). Condition: change >= +9%
        # AND price pinned at the day high (frozen).
        if (
            isinstance(day_frac, (int, float))
            and day_frac * 100.0 >= 9.0
            and price and q.get("high") and price >= q["high"]
        ):
            from eod_bot import net_return_pct
            outcomes.append({
                "symbol": pick["symbol"],
                "pick_date": pick["pick_date"],
                "entry_price": pick["entry_price"],
                "exit_price": price,
                "outcome": "PURGE-LOCK",
                "net_return_pct": round(
                    net_return_pct(pick["entry_price"], price), 3
                ),
                "closed_at_utc": now_utc.isoformat(),
                "entry_score": pick.get("score"),
            })
            continue

        # v2.6.0: morning-fade picks carry their own exit plan - sell
        # at open+5min (default), hard stop on a gap-down open, +15min
        # on a weak/flat open. The ladder is evaluated on the FIRST
        # trace tick past the planned minute; the plan travels on the
        # pick so every rescue slot re-derives the same decision. The
        # open price comes from the session-opens memory (first print
        # of the session), never from a later quote.
        strategy = pick.get("strategy")
        if strategy == "morning-fade":
            import morning_fade as _mf
            from session_opens import open_of
            open_price = open_of(opens_state, today, pick["symbol"])
            if open_price and pick.get("_open_seen") != today:
                plan = _mf.exit_plan(pick["entry_price"], open_price)
                pick["exit_plan_exec"] = plan
                pick["_open_seen"] = today
                print(
                    f"trace: {pick['symbol']} opened {open_price} - "
                    f"{plan['action']} at open+{plan['at_min']}min ({plan['reason']})"
                )
            plan = pick.get("exit_plan_exec") or {
                "action": "SELL", "at_min": _mf.OPEN_SELL_MIN, "reason": "default"
            }
            open_min_utc = 4 * 60 + 35   # 09:35 PKT = first trace slot
            planned_min = open_min_utc + int(plan.get("at_min", _mf.OPEN_SELL_MIN))
            sell_now = plan.get("action") in ("SELL_NOW", "SELL_FIRST_PRINT") or minutes >= planned_min
            if sell_now and price:
                from eod_bot import net_return_pct
                outcomes.append({
                    "symbol": pick["symbol"],
                    "pick_date": pick["pick_date"],
                    "entry_price": pick["entry_price"],
                    "exit_price": price,
                    "outcome": "OPEN-SELL" if plan.get("action") != "SELL_NOW" else "GAP-STOP",
                    "exit_reason": plan.get("reason"),
                    "net_return_pct": round(
                        net_return_pct(pick["entry_price"], price), 3
                    ),
                    "closed_at_utc": now_utc.isoformat(),
                    "entry_score": pick.get("score"),
                    "strategy": "morning-fade",
                })
                continue
            # Fall through to the classic barriers as safety net until
            # the planned minute arrives.
        closed = trace_pick(pick, snapshot, now_utc)
        if closed:
            if strategy == "morning-fade":
                closed["strategy"] = "morning-fade"
            outcomes.append(closed)
        else:
            # Past force-close and still open? Close at last known price.
            if minutes >= FORCE_CLOSE_MIN_UTC + 90 and price:
                from eod_bot import net_return_pct
                outcomes.append({
                    "symbol": pick["symbol"],
                    "pick_date": pick["pick_date"],
                    "entry_price": pick["entry_price"],
                    "exit_price": price,
                    "outcome": "FORCE",
                    "net_return_pct": round(
                        net_return_pct(pick["entry_price"], price), 3
                    ),
                    "closed_at_utc": now_utc.isoformat(),
                    "entry_score": pick.get("score"),
                })
            else:
                still_open.append(pick)

    if outcomes:
        append_ledger(LEDGER, outcomes)
        tracker["open"] = still_open
        save_json(TRACKER, tracker)

    summary = ledger_summary(LEDGER)
    SIGNALS_MD.write_text(
        render_morning_md(summary, outcomes, len(still_open)),
        encoding="utf-8",
    )
    stamp_heartbeat("trace")

    # v2.2.0 SELF-LEARNING: after outcomes land, let the ledger re-fit
    # the weights. Quiet when there isn't enough evidence yet; writes
    # data/refit.json only when a feature has truly earned a move.
    # v3.0.0 owner simplification: the auto-refit is retired - the
    # ledger keeps landing outcomes, but no run rewrites the weights.
    if eod_bot.MEMORY_LAYERS_ENABLED:
        try:
            import weekly_refit

            report = weekly_refit.refit(weekly_refit.read_ledger())
            prev = load_json(REFIT, None)
            if report and (
                not prev or report["generated"] != prev.get("generated")
            ):
                weekly_refit.apply_refit(report)
                print(
                    "refit: weights updated - "
                    f"{report['features_moved']} feature(s) moved"
                )
        except Exception as exc:  # learning must never break the trace
            print(f"refit: skipped ({exc})")

    # Delivery (v2.0.3) - independent channels, same contract as the
    # pick: a GitHub failure can never silence Telegram.
    if outcomes:
        state = load_notified()
        key = f"trace:{today}:{[o['symbol'] for o in outcomes]}"
        dirty = False

        body = (
            f"@muhammadrehanqureshi **Morning outcomes**\n"
            + "\n".join(
                f"{o['symbol']}: {o['outcome']} at {o['exit_price']:.2f} "
                f"({o['net_return_pct']:+.2f}% net)"
                for o in outcomes
            )
        )

        if token and key + ":gh" not in state["posted"]:
            try:
                issue = ensure_issue(token)
                if issue and post_event(token, issue, body):
                    state["posted"].append(key + ":gh")
                    dirty = True
            except Exception:  # noqa: BLE001 - email channel, never fatal
                print("trace: github email path unreachable (non-fatal)")

        if key + ":tg" not in state["posted"]:
            try:
                import telegram_notify

                if telegram_notify.send_outcomes(today, outcomes):
                    state["posted"].append(key + ":tg")
                    dirty = True
                    print("trace: telegram delivered")
            except Exception:  # noqa: BLE001 - backup, never fatal
                pass

        if dirty:
            save_notified(state)

    print(
        f"trace: {len(outcomes)} closed, {len(still_open)} open | "
        f"ledger {summary.get('trades', 0)} trades, "
        f"{summary.get('win_rate_pct', 0)}% wins"
    )
    # v3.4.0 session cards: MARKET CLOSED card on both channels -
    # outcomes are in, the bots sleep until the next market day.
    # Once per day; kill-switch session_cards_enabled; never fatal.
    try:
        import session_cards

        _card_ok, _card_note = session_cards.announce_close()
        if _card_ok:
            print(f"session card: {_card_note}")
    except Exception as _card_exc:  # noqa: BLE001
        print(f"session card error (non-fatal): {_card_exc}")
    return 0


def mode_close_card() -> int:
    """v3.5.0: the MARKET CLOSED card, every market day.

    Fired by the after-close cron (15:36 PKT Mon-Thu / 16:36 PKT
    Friday). Idempotent (session_cards dedupes), silent when the
    market is somehow still open, never fatal.
    """
    try:
        import session_cards

        ok, note = session_cards.announce_close()
        print(f"close card: {note}")
        return 0 if ok or "already sent" in note or "waits" in note else 0
    except Exception as exc:  # noqa: BLE001 - a card must never fail a run
        print(f"close card error (non-fatal): {exc}")
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sentinel-EOD runner")
    parser.add_argument(
        "mode", choices=["reference", "pick", "trace", "status", "close-card"]
    )
    parser.add_argument("--token", default=None)
    parser.add_argument(
        "--window-open", action="store_true",
        help="pick mode: store the :00 window-open tape only (no card)",
    )
    args = parser.parse_args(argv)

    if args.mode == "reference":
        return mode_reference(args.token)
    if args.mode == "pick":
        return mode_pick(args.token, window_open=args.window_open)
    if args.mode == "trace":
        return mode_trace(args.token)
    if args.mode == "close-card":
        return mode_close_card()

    summary = ledger_summary(LEDGER)
    tracker = load_json(TRACKER, {"open": []})
    print(json.dumps({"ledger": summary,
                      "open": len(tracker.get("open", []))}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
