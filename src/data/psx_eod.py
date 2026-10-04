"""PSX DPS EOD downloader — self-contained port of the verified fetch layer.

Provenance: endpoint, headers, row layout, and retry policy are ported from
the owner's existing `the-sentinel` bot (`src/scan_positive_opens.py`),
where the row layout `[epoch, close, volume, open]` was verified against a
live poll snapshot (MLCF, 2026-09-08). One GET returns the FULL history
(~1,240 sessions ≈ 5 years) per symbol.

Row limitation (documented, not hidden): DPS timeseries provides
open/close/volume only — no high/low. Backtests must therefore run in
`close`-touch mode (see src/backtest/engine.py) and say so in their reports.

Universe: KMIALL tickers are loaded from the owner's local sentinel data
file (not committed). Rows carry `listedIn` containing "KMIALLSHR".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DPS_TIMESERIES_URL = "https://dps.psx.com.pk/timeseries/eod/{symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 20.0
REQUEST_PAUSE = 0.35   # polite: ~307 symbols ≈ a few minutes
RETRIES = 3


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_eod(symbol: str, http: requests.Session) -> list[dict] | None:
    """Full EOD history for one symbol, oldest first.

    Returns list of {"date", "open", "close", "volume"} dicts.
    None  = fetch failed after retries (network/5xx) — caller must treat
            this as a data-quality failure (GOVERNANCE SO-3: never fill gaps
            with fabricated rows).
    []    = valid response, symbol genuinely has no history.
    """
    url = DPS_TIMESERIES_URL.format(symbol=symbol)
    for attempt in range(1, RETRIES + 1):
        try:
            resp = http.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            resp = None
        if resp is not None and resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if payload is not None and payload.get("status") == 1:
                out: list[dict] = []
                for row in payload.get("data") or []:
                    epoch, close, volume, open_ = row[0], row[1], row[2], row[3]
                    day = datetime.fromtimestamp(epoch, tz=timezone.utc).date()
                    out.append({
                        "date": day,
                        "open": float(open_),
                        "close": float(close),
                        "volume": float(volume),
                    })
                out.sort(key=lambda r: r["date"])
                return out
            return []
        if attempt < RETRIES:
            time.sleep(1.5 * attempt)
    return None


def load_universe(path: Path) -> list[str]:
    """KMIALL symbols from the sentinel's kmiall_tickers.json.

    Keeps rows listed in KMIALLSHR. Raises loudly if the file is missing —
    the universe must be explicit, never silently empty.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"KMIALL universe file not found: {path}. "
            f"Point --universe at the sentinel's data/kmiall_tickers.json."
        )
    rows = json.loads(path.read_text(encoding="utf-8"))
    symbols = [
        r["symbol"]
        for r in rows
        if "KMIALLSHR" in (r.get("listedIn") or [])
    ]
    if not symbols:
        raise ValueError(f"No KMIALLSHR symbols found in {path}")
    return sorted(set(symbols))


# ---------------------------------------------------------------------------
# Dataset build (local only — data/ is gitignored)
# ---------------------------------------------------------------------------

def build_dataset(
    symbols: list[str],
    cache_dir: Path,
    out_path: Path,
    pause: float = REQUEST_PAUSE,
) -> pd.DataFrame:
    """Download (with per-symbol cache) and combine into one long frame.

    Columns: symbol, date, open, close, volume — sorted by (symbol, date).
    Per-symbol JSON caches make re-runs incremental and offline-friendly.
    Symbols whose fetch failed are recorded in out_path.with_suffix('.failures')
    and excluded — the report must state this count (SO-3 honesty).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    http = requests.Session()
    http.headers.update(HEADERS)

    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for i, sym in enumerate(symbols, 1):
        cache = cache_dir / f"{sym}.json"
        if cache.is_file():
            rows = json.loads(cache.read_text(encoding="utf-8"))
            if rows is None:
                failures.append(sym)
                continue
        else:
            rows = fetch_eod(sym, http)
            cache.write_text(json.dumps(rows), encoding="utf-8")
            time.sleep(pause)
        if rows is None:
            failures.append(sym)
            continue
        if not rows:
            continue
        frames.append(pd.DataFrame(rows).assign(symbol=sym))
        if i % 25 == 0:
            print(f"  {i}/{len(symbols)} symbols done", flush=True)

    (out_path.parent / (out_path.stem + ".failures")).write_text(
        json.dumps({"failed_symbols": failures,
                    "fetched": len(symbols) - len(failures)}),
        encoding="utf-8",
    )
    if not frames:
        raise RuntimeError("No symbol data fetched — dataset build aborted.")
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df.to_csv(out_path, index=False, compression="gzip" if out_path.suffix == ".gz" else None)
    print(f"Dataset: {len(df):,} rows, {df['symbol'].nunique()} symbols "
          f"-> {out_path} (failures: {len(failures)})")
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build local PSX KMIALL EOD dataset")
    ap.add_argument("--universe", type=Path, required=True,
                    help="Path to sentinel's kmiall_tickers.json (local)")
    ap.add_argument("--out", type=Path, default=Path("data/eod_dataset.csv.gz"))
    ap.add_argument("--cache-dir", type=Path, default=Path("data/raw_eod"))
    args = ap.parse_args(argv)

    symbols = load_universe(args.universe)
    print(f"Universe: {len(symbols)} KMIALL symbols")
    build_dataset(symbols, args.cache_dir, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
