#!/usr/bin/env python3
"""One-shot daily signal job: ensure today's bars, then push (SO-10).

Runs on GitHub Actions (owner approval, 2026-10-07) and on the owner's PC
for manual trials. Bounded by design: it fetches only a small trailing EOD
window (100 calendar days, safely inside the CI guard in
scripts/build_eod_history.py), never the 5-year history (SO-4). The
canonical dataset on the PC is never touched: this job writes its own
window file.

Why a window is enough: every engine feature at T looks back at most 21
bars (MA20, relvol median, sweep 16, regime 20), so a 100-day window
computes bit-identical features for the newest session.

Steps:
  1. resolve the KMIALL universe: the sentinel's kmiall_tickers.json when
     present (PC), else the tracked copy src/data/universe_kmiall.json;
  2. fetch the trailing window from the PSX portal into
     data/eod_signal_window.csv.gz;
  3. filter to the universe, dedupe on (date, symbol), and write
     data/eod_history_signal.csv.gz;
  4. hand over to src.signals.signal_push (RELAY_ADMIN_TOKEN from the
     environment or repo .env; relay URL from data/relay_url.txt or the
     known default).

Usage:
    python scripts/signal_daily.py            # real post-close push
    python scripts/signal_daily.py --dry-run  # verdict only, sends nothing
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.psx_eod import load_universe  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

UNIVERSE_FALLBACK = ROOT / "src" / "data" / "universe_kmiall.json"
UNIVERSE_LEGACY = ROOT / "data" / "legacy_sentinel" / "data" / "kmiall_tickers.json"
WINDOW_DAYS = 100
WINDOW_RAW = ROOT / "data" / "eod_signal_window.csv.gz"
WINDOW_KMI = ROOT / "data" / "eod_history_signal.csv.gz"
DEFAULT_RELAY = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def fetch_window(kdate) -> None:
    start = (kdate - timedelta(days=WINDOW_DAYS)).isoformat()
    end = kdate.isoformat()
    print(f"fetching EOD window {start} .. {end} from the PSX portal ...")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_eod_history.py"),
         "--start", start, "--end", end, "--out", str(WINDOW_RAW)],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise SystemExit("window fetch failed; the signal push did NOT run")


def filter_to_universe() -> None:
    import pandas as pd

    path = UNIVERSE_LEGACY if UNIVERSE_LEGACY.is_file() else UNIVERSE_FALLBACK
    syms = set(load_universe(path))
    print(f"universe: {len(syms)} KMIALL symbols from {path.name}")
    df = pd.read_csv(WINDOW_RAW, parse_dates=["date"])
    df = df[df["symbol"].isin(syms)]
    df = df.drop_duplicates(subset=["date", "symbol"], keep="last")
    df = df.sort_values(["symbol", "date"])
    df.to_csv(WINDOW_KMI, index=False)
    sessions = df["date"].dt.date.nunique()
    print(f"signal window: {len(df):,} rows x {df['symbol'].nunique()} symbols "
          f"x {sessions} sessions -> {WINDOW_KMI.name}")


def relay_url_file() -> None:
    p = ROOT / "data" / "relay_url.txt"
    if not p.is_file():
        url = os.environ.get("RELAY_URL", DEFAULT_RELAY).rstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(url + "\n", encoding="utf-8")
        print(f"relay url written ({url})")


def relay_preflight() -> str:
    """Check the relay and the admin token BEFORE fetching the window.

    Owner bug report, 2026-10-10: the scheduled job reported "the daily
    signal push failed" with no cause. Most of the failures it can hit are
    cheap to detect and expensive to discover: the EOD window fetch takes
    minutes, so a rotated token or an unpaired relay was only announced
    after the whole job had run. This runs first and names the reason.
    """
    from src.notify.schedule_runner import load_relay_url
    from src.signals.signal_push import read_admin_token, relay_preflight as check

    try:
        token = read_admin_token()
    except RuntimeError as exc:
        return str(exc)
    return check(load_relay_url(), token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="daily signal job (SO-10)")
    ap.add_argument("--dry-run", action="store_true",
                    help="verdict only, sends nothing")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="push without checking the relay and token first")
    args = ap.parse_args(argv)

    if not args.dry_run and not args.skip_preflight:
        blocked = relay_preflight()
        if blocked:
            print(f"PREFLIGHT FAILED: {blocked}")
            print("the EOD fetch was skipped: a push could not have succeeded.")
            return 1

    kdate = now_karachi().date()
    fetch_window(kdate)
    filter_to_universe()
    relay_url_file()

    from src.signals.signal_push import main as push_main

    push_args = ["--dataset", str(WINDOW_KMI)]
    if args.dry_run:
        push_args.append("--dry-run")
    return push_main(push_args)


if __name__ == "__main__":
    raise SystemExit(main())
