"""Sentinel-EOD - PC-direct emergency pick sender (tier 3, v2.0.4).

WHY THIS EXISTS: every delivery tier above this one still ends in
GitHub Actions - the cron slots, the watchdog rescues, even the
spark's Guard C dispatch. If Actions itself is down at :26, with the
primary (:21), backup (:24) and watchdogs (:26/:28) all missed, this
PKT (API outage, queued runners, dead indexer), NO run anywhere can
deliver anything. The owner's standing order is: "if GitHub tries to
fuck me, Telegram saves me." This tier makes that literal:

  * runs ON THE OWNER'S PC from the spark (Windows Task Scheduler,
    already active every 5 minutes);
  * polls the PSX feed DIRECTLY (the EOD repo's production poll path);
  * scores with the EOD repo's production scorer (kept fresh in
    data/_eod_src_current - a depth-1 clone the spark maintains);
  * sends Telegram DIRECTLY (token from a gitignored local secrets
    file) - api.github.com is never touched on the delivery path;
  * publishes pick + tracker + notified state in the local clone and
    then PUSHES it back to the EOD repo - so when GitHub recovers,
    its own day-guard sees today's book and never double-publishes.

TIMING: arms at :26 past the hour (window to :28). The tiers above
own the on-time :21-:25 delivery; if Actions is alive at all,
something has published by ~:23. This tier exists for when it is
not - a :26/:28 pick beats no pick, and the owner still orders at
:29 (the v2.2.1 contract: nothing delivers after :28).

DEDUP: one emergency send per day (data/.eod_emergency_state), plus
the fresh-clone pick-date check right before sending.

The decision core (emergency_pick_decision) is pure and unit-tested.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

PKT = timezone(timedelta(hours=5))
EOD_REPO_URL = "https://github.com/muhammadrehanqureshi/sentinel-eod.git"

# The disaster window (v2.2.1): GitHub had every chance (primary
# :21, backup :24, watchdogs :26/:28 dispatch). If the pick still
# does not exist at :26, Actions is dead and this tier takes over -
# :26-:28, the last minutes a pick the owner can still act on
# (he places his order at :29). Nothing arms after :28.
WINDOW_MON_THU = ((15, 26), (15, 28))
WINDOW_FRIDAY = ((16, 26), (16, 28))

REPO = Path(__file__).resolve().parents[1]
SECRETS = REPO / "data" / "eod_telegram_secrets.json"
STATE = REPO / "data" / ".eod_emergency_state"
EOD_SRC = REPO / "data" / "_eod_src_current"   # the maintained EOD clone


def emergency_pick_decision(
    now_pkt: datetime,
    pick_published_today: bool,
    telegram_ready: bool,
) -> tuple[bool, str]:
    """Pure decision core - unit-tested. (act?, reason)"""
    if now_pkt.weekday() >= 5:
        return False, "weekend"
    mins = now_pkt.hour * 60 + now_pkt.minute
    start, end = (
        WINDOW_FRIDAY if now_pkt.weekday() == 4 else WINDOW_MON_THU
    )
    s, e = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if mins < s:
        return False, f"before emergency window ({start[0]:02d}:{start[1]:02d})"
    if mins > e:
        return False, f"after emergency window ({end[0]:02d}:{end[1]:02d})"
    if pick_published_today:
        return False, "pick already published today"
    if not telegram_ready:
        return False, "telegram not configured on this PC"
    return True, (
        f"no pick by {start[0]:02d}:{start[1]:02d} and GitHub had its "
        "chance - PC-direct emergency tier armed"
    )


def _git_env() -> dict:
    import os

    env = dict(os.environ)
    env["GCM_INTERACTIVE"] = "Never"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def ensure_eod_clone() -> bool:
    """The EOD repo clone at EOD_SRC, refreshed. False only when there
    is no usable clone AND a fresh one could not be made (offline AND
    never cloned - then scoring locally is impossible)."""
    try:
        if (EOD_SRC / ".git").exists():
            subprocess.run(
                ["git", "-C", str(EOD_SRC), "pull", "--ff-only", "origin", "main"],
                capture_output=True, timeout=60, env=_git_env(),
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if sys.platform == "win32" else 0),
            )
            return (EOD_SRC / "src" / "run_eod.py").exists()
        if EOD_SRC.exists():
            shutil.rmtree(EOD_SRC, ignore_errors=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", EOD_REPO_URL, str(EOD_SRC)],
            capture_output=True, timeout=120, env=_git_env(),
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                           if sys.platform == "win32" else 0),
        )
        return (EOD_SRC / "src" / "run_eod.py").exists()
    except Exception:
        return (EOD_SRC / "src" / "run_eod.py").exists()


def sync_state_to_github() -> str:
    """Commit + push any pick state the emergency run left in the
    clone. Idempotent; retried by the spark on later runs until it
    lands, so GitHub's recovery can never double-publish.

    v2.0.5: reconcile BEFORE pushing. A clone left behind by a disabled
    spark (2026-09-18..24) made every push a non-fast-forward rejection
    and the recovery duty silently never landed. The clone is refreshed
    first (ensure_eod_clone); if origin still moved past local commits,
    the local state is rebased onto origin and the push retried once.
    A rebase conflict aborts cleanly - the next spark tick retries.
    """
    if not (EOD_SRC / ".git").exists():
        return "no clone"
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             if sys.platform == "win32" else 0)
    try:
        ensure_eod_clone()
        st = subprocess.run(
            ["git", "-C", str(EOD_SRC), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30, env=_git_env(),
            creationflags=flags,
        ).stdout
        if st.strip():
            subprocess.run(
                ["git", "-C", str(EOD_SRC), "add", "-A", "data/", "SIGNALS.md"],
                capture_output=True, timeout=30, env=_git_env(),
                creationflags=flags,
            )
            # A fresh clone has no git identity - carry the owner's
            # explicitly (AGENTS.md: commits are authored as the owner).
            subprocess.run(
                ["git", "-C", str(EOD_SRC),
                 "-c", "user.name=Mr. Rehan",
                 "-c", "user.email=muhammadrehanqureshi@users.noreply.github.com",
                 "commit", "-m", "emergency pick (PC-direct tier 3)"],
                capture_output=True, timeout=30, env=_git_env(),
                creationflags=flags,
            )
        push = subprocess.run(
            ["git", "-C", str(EOD_SRC), "push", "origin", "main"],
            capture_output=True, text=True, timeout=60, env=_git_env(),
            creationflags=flags,
        )
        if push.returncode != 0:
            # Rejected or stale refs: rebase local state onto origin and
            # retry once. A conflict aborts the rebase cleanly and the
            # next spark tick retries the whole duty.
            subprocess.run(
                ["git", "-C", str(EOD_SRC), "rebase", "--abort"],
                capture_output=True, timeout=30, env=_git_env(),
                creationflags=flags,
            )
            subprocess.run(
                ["git", "-C", str(EOD_SRC), "pull", "--rebase", "origin", "main"],
                capture_output=True, timeout=60, env=_git_env(),
                creationflags=flags,
            )
            push = subprocess.run(
                ["git", "-C", str(EOD_SRC), "push", "origin", "main"],
                capture_output=True, text=True, timeout=60, env=_git_env(),
                creationflags=flags,
            )
        return "pushed" if push.returncode == 0 else f"push failed: {push.stderr[:80]}"
    except Exception as exc:  # noqa: BLE001
        return f"sync error: {exc}"


def _secrets() -> tuple[str, str] | None:
    try:
        cfg = json.loads(SECRETS.read_text(encoding="utf-8"))
        tok = (cfg.get("bot_token") or "").strip()
        chat = (cfg.get("chat_id") or "").strip()
        if tok and chat:
            return tok, chat
    except Exception:
        pass
    return None


def send_telegram(message: str) -> bool:
    """Direct send, 4 attempts with backoff - this is the last line
    of defense; the channel must survive the flaky route."""
    cfg = _secrets()
    if cfg is None:
        return False
    tok, chat = cfg
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                data=json.dumps(
                    {"chat_id": chat, "text": message, "parse_mode": "HTML"}
                ).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:  # noqa: BLE001 - last-resort channel
            pass
        if attempt < 3:
            time.sleep(2 * (attempt + 1))
    return False


def _already_sent_today() -> bool:
    try:
        return STATE.read_text(encoding="utf-8").strip() == (
            datetime.now(PKT).date().isoformat()
        )
    except Exception:
        return False


def _mark_sent_today() -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(datetime.now(PKT).date().isoformat(), encoding="utf-8")


def run_emergency_pick() -> int:
    """The real tier-3 path: refresh the clone, decide, poll the feed,
    score, publish locally, push state back, send Telegram DIRECT."""
    now = datetime.now(PKT)
    today = now.date().isoformat()

    if not ensure_eod_clone():
        print("emergency: no usable EOD scorer clone - cannot run")
        return 1

    # Final stand-down check on the freshest clone data (a GitHub run
    # may have published seconds ago).
    tracker = {}
    try:
        tracker = json.loads(
            (EOD_SRC / "data" / "tracker.json").read_text(encoding="utf-8")
        )
    except Exception:
        pass
    published = tracker.get("pick_date") == today or (
        EOD_SRC / "data" / "picks" / f"{today}.json"
    ).exists()

    act, reason = emergency_pick_decision(
        now, published or _already_sent_today(), _secrets() is not None
    )
    print(f"emergency: {reason}")
    if not act:
        return 0

    # Production scorer, straight from the clone.
    sys.path.insert(0, str(EOD_SRC / "src"))
    import run_eod  # noqa: E402  (clone path inserted above)

    try:
        snapshot = run_eod.poll_kse100_quotes()
    except Exception as exc:  # noqa: BLE001
        print(f"emergency: feed poll failed - {exc}")
        return 1

    baselines = run_eod.load_json(run_eod.BASELINES, None) or {}
    reference = run_eod.load_json(run_eod.REFERENCE, None) or {}
    hist = run_eod.load_json(run_eod.CLOSE_HISTORY, None) or {"sessions": {}}
    snapshot["_date"] = today  # stale-reference guard must see today
    sector_flow = run_eod.compute_sector_flow(snapshot)
    rows = run_eod.build_cross_section(
        snapshot, reference, baselines, sector_flow,
        run_eod.session_history_map(hist, today),
    )
    sess_hist = run_eod.session_history_map(hist, today)
    picks = run_eod.pick_top(rows, close_history=sess_hist)

    # Book-keeping AFTER scoring (v2.1.2 contract - same order as the
    # production runner: today's data must never dilute its own
    # features, and the streak memory must never lose a day).
    run_eod.update_baselines(snapshot.get("quotes") or {})
    run_eod.update_close_history(snapshot.get("quotes") or {}, today)

    if not picks:
        # ALL-LIVE card: even the emergency tier must deliver the
        # data-driven "stand aside" - silence is never ambiguous. Names
        # the next market day (owner's order).
        wd = now.weekday()
        nxt = ("Monday" if wd == 4 else
               ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                "Sunday", "Monday"][(wd + 1) % 7])
        payload = {"pick_date": today, "picked_at_pkt": now.isoformat(),
                   "picks": [],
                   "note": f"emergency: no live candidate - no buying for {nxt}"}
        run_eod.save_json(run_eod.PICKS_DIR / f"{today}.json", payload)
        run_eod.stamp_heartbeat("pick")
        mkt = run_eod.kse100_change_pct(snapshot)
        if send_telegram(
            "⭕ <b>Sentinel-EOD - NO LIVE CANDIDATE - NO BUYING FOR "
            f"{nxt.upper()}</b> (PC-direct emergency path). Every name "
            "failed the data test: dead final-hour tape / streak "
            "exhaustion / liquidity. The bot ran and decided: stand aside."
            + (f" Market: KSE-100 {mkt:+.2f}%." if mkt is not None else "")
        ):
            _mark_sent_today()
            print("emergency: ALL-LIVE card delivered via Telegram DIRECT")
            print(f"emergency: state sync - {sync_state_to_github()}")
        return 0

    payload = {"pick_date": today, "picked_at_pkt": now.isoformat(), "picks": picks}

    # Publish in the clone (paper trail + push-back state).
    run_eod.save_json(run_eod.PICKS_DIR / f"{today}.json", payload)
    tracker["open"] = [{**p, "pick_date": today} for p in picks]
    tracker["pick_date"] = today
    run_eod.save_json(run_eod.TRACKER, tracker)
    run_eod.stamp_heartbeat("pick")

    # Telegram DIRECT - the whole point. No GitHub on this path.
    mkt = run_eod.kse100_change_pct(snapshot)
    lines = [
        f"🚨 <b>Sentinel-EOD - picks for {today}</b> (PC-direct emergency)",
        "GitHub was unreachable - your PC delivered this. "
        "Buy at the close. Next market day: sell at +2.0%, "
        "stop -1.0%, force-close 11:30 PKT.",
    ]
    if mkt is not None:
        lines.insert(2, f"Market at analysis: KSE-100 {mkt:+.2f}%")
    lines.append("")
    for i, p in enumerate(picks, 1):
        flag = f"\n   {p['streak_flag']}" if p.get("streak_flag") else ""
        lines.append(
            f"{i}. <b>{p['symbol']}</b> - entry ~{p['entry_price']:.2f} "
            f"(score {p['score']:.3f}){flag}"
        )
    if send_telegram("\n".join(lines)):
        _mark_sent_today()
        print(f"emergency: {len(picks)} picks delivered via Telegram DIRECT")
        print(f"emergency: state sync - {sync_state_to_github()}")
        return 0
    print("emergency: telegram delivery FAILED after retries")
    return 1


if __name__ == "__main__":
    sys.exit(run_emergency_pick())
