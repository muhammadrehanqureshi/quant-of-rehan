"""Data-quality audit for the 5m/15m/30m/60m archive.

All session times are Asia/Karachi, a fixed UTC+5. The audit does not fill,
repair or resample anything. It counts what exists,
what is missing, and which records are structurally impossible, so the
strategy layer can exclude a symbol or a year instead of pretending the
archive is uniform.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.sessions import KARACHI
from src.research.intraday100 import TIMEFRAME_SECONDS
from src.research.intraday100.data import attach_sessions, load_timeframe

DASHES = "\u2014\u2013\u2012\u2015\u2e3a\u2e3b"


def _clean(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _quantiles(values: pd.Series) -> dict[str, float | None]:
    if values.empty:
        return {}
    q = values.quantile([0.0, 0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 1.0])
    return {str(k): _clean(v) for k, v in q.items()}


def audit_timeframe(root: str | Path, timeframe: str) -> dict[str, Any]:
    seconds = TIMEFRAME_SECONDS[timeframe]
    df = load_timeframe(root, timeframe)
    if df.empty:
        return {"timeframe": timeframe, "status": "empty"}

    df = attach_sessions(df, timeframe)
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(KARACHI).dt.date
    df["year"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(KARACHI).dt.year

    duplicates = int(df.duplicated(["symbol", "ts"]).sum())
    off_grid = int((df["ts"] % seconds != 0).sum())
    invalid_high = int((df["high"] < df[["open", "close", "low"]].max(axis=1)).sum())
    invalid_low = int((df["low"] > df[["open", "close", "high"]].min(axis=1)).sum())
    nonpositive_price = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    negative_volume = int((df["volume"] < 0).sum())
    zero_volume = int((df["volume"] == 0).sum())
    non_regular = int((~df["regular"]).sum())
    invalid_bar = int((~df["valid_bar"]).sum())

    per_sd = (
        df.groupby(["symbol", "date", "year"], observed=True)
        .agg(bars=("ts", "size"), first_ts=("ts", "min"), last_ts=("ts", "max"),
             volume=("volume", "sum"))
        .reset_index()
    )
    market_bars = df.groupby("date")["ts"].nunique().rename("market_bars")
    per_sd = per_sd.merge(market_bars, on="date", how="left")
    per_sd["coverage"] = per_sd["bars"] / per_sd["market_bars"].replace(0, np.nan)

    per_symbol = (
        per_sd.groupby("symbol", observed=True)
        .agg(sessions=("date", "nunique"), bars=("bars", "sum"),
             median_coverage=("coverage", "median"),
             first_date=("date", "min"), last_date=("date", "max"))
        .reset_index()
    )
    per_symbol["below_50pct"] = per_symbol["median_coverage"] < 0.50
    per_symbol = per_symbol.sort_values(["median_coverage", "symbol"])

    per_year = (
        per_sd.groupby("year", observed=True)
        .agg(bars=("bars", "sum"), symbols=("symbol", "nunique"),
             sessions=("date", "nunique"), median_coverage=("coverage", "median"))
        .reset_index()
    )
    per_year["below_50pct_symbols"] = [
        int((per_sd[per_sd["year"] == year].groupby("symbol")["coverage"].median() < 0.50).sum())
        for year in per_year["year"]
    ]
    year_totals = df.groupby("year", observed=True).size().rename("rows")
    per_year = per_year.merge(year_totals, left_on="year", right_index=True, how="left")

    df_sorted = df.sort_values(["symbol", "ts"], kind="mergesort")
    interval = df_sorted.groupby("symbol", sort=False)["ts"].diff()
    # Compare bands, not whole days: the Friday midday break is a real market
    # closure, not a missing-bar gap inside a continuous session.
    same_band = df_sorted.groupby("symbol", sort=False)["band_key"].diff().eq(0)
    gap_seconds = interval.where(same_band)
    expected_gap = int((gap_seconds == seconds).sum())
    missing_gap = int((gap_seconds > seconds).sum())
    duplicate_gap = int((gap_seconds == 0).sum())

    prev_close = df_sorted.groupby("symbol", sort=False)["close"].shift(1)
    open_gap = df_sorted["open"] / prev_close - 1.0
    close_gap = df_sorted["close"] / prev_close - 1.0
    large_open_gap = int((open_gap.abs() > 0.20).sum())
    large_close_gap = int((close_gap.abs() > 0.20).sum())
    gap_by_symbol = (
        pd.DataFrame({"symbol": df_sorted["symbol"], "open_gap": open_gap.abs(),
                      "close_gap": close_gap.abs()})
        .groupby("symbol", observed=True)
        .agg(max_open_gap=("open_gap", "max"), max_close_gap=("close_gap", "max"),
             gap_20_count=("open_gap", lambda s: int((s > 0.20).sum())))
        .reset_index()
        .sort_values(["gap_20_count", "max_open_gap"], ascending=False)
        .head(20)
    )

    all_dates = sorted(per_sd["date"].unique())
    first_date, last_date = all_dates[0], all_dates[-1]
    calendar = pd.date_range(first_date, last_date, freq="D").date
    expected_weekdays = [
        d for d in calendar
        if d.weekday() < 5 and (d.month, d.day) not in {(11, 9), (12, 25)}
    ]
    # The yearly holiday list is only complete for 2026, so missing weekdays
    # are reported as a list, not silently classified as holidays.
    missing_weekdays = [d for d in expected_weekdays if d not in set(all_dates)]

    summary = {
        "timeframe": timeframe,
        "status": "ok",
        "bar_seconds": seconds,
        "rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "sessions": int(df["date"].nunique()),
        "first_ts": int(df["ts"].min()),
        "last_ts": int(df["ts"].max()),
        "first_datetime_pkt": datetime.fromtimestamp(int(df["ts"].min()), tz=KARACHI).isoformat(),
        "last_datetime_pkt": datetime.fromtimestamp(int(df["ts"].max()), tz=KARACHI).isoformat(),
        "first_date": first_date.isoformat(),
        "last_date": last_date.isoformat(),
        "duplicates": duplicates,
        "off_grid_timestamps": off_grid,
        "invalid_high_rows": invalid_high,
        "invalid_low_rows": invalid_low,
        "nonpositive_price_rows": nonpositive_price,
        "negative_volume_rows": negative_volume,
        "zero_volume_rows": zero_volume,
        "non_regular_rows": non_regular,
        "invalid_bar_rows": invalid_bar,
        "expected_gap_rows": expected_gap,
        "missing_gap_rows": missing_gap,
        "duplicate_gap_rows": duplicate_gap,
        "large_open_gap_rows": large_open_gap,
        "large_close_gap_rows": large_close_gap,
        "coverage_quantiles": _quantiles(per_sd["coverage"]),
        "symbols_below_50pct": int(per_symbol["below_50pct"].sum()),
        "symbols_below_75pct": int((per_symbol["median_coverage"] < 0.75).sum()),
        "per_year": per_year.to_dict(orient="records"),
        "lowest_coverage_symbols": per_symbol.head(25).to_dict(orient="records"),
        "largest_gap_symbols": gap_by_symbol.to_dict(orient="records"),
        "weekday_slots": len(expected_weekdays),
        "missing_weekday_slots": len(missing_weekdays),
        "missing_weekday_sample": [d.isoformat() for d in missing_weekdays[:40]],
        "note": (
            "ts is UTC epoch seconds. Karachi wall clock is ts + 5 hours. "
            "Missing bars are not filled. The yearly holiday list is complete "
            "only for 2026, so weekday absences before 2026 may be holidays, "
            "suspensions or archive gaps and are not classified here."
        ),
    }
    return _clean(summary)


def audit_archive(root: str | Path) -> dict[str, Any]:
    result = {
        "archive_root": str(Path(root)),
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "timeframes": {},
        "limitations": [
            "No 1-minute archive exists.",
            "Historical KMIALL membership and corporate-action files are unavailable.",
            "The current 319-symbol universe is applied to every year; this is survivorship-biased.",
            "There are no historical quotes, so execution uses a documented cost and spread proxy.",
            "Trading halts, circuit breakers and symbol changes are not in the archive.",
        ],
    }
    for timeframe in TIMEFRAME_SECONDS:
        result["timeframes"][timeframe] = audit_timeframe(root, timeframe)
    return result


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def data_quality_markdown(audit: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append("PSX KMIALL intraday archive, five years and four intraday timeframes. "
                 "The archive also carries a 1D partition; this audit is scoped to the "
                 "intraday frames the pilot reads.")
    lines.append("")
    lines.append("## Scope and hard limitations")
    lines.append("")
    for item in audit["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("The audit is descriptive. It never fills a missing bar, never "
                 "resamples a 5m bar into a higher timeframe, and never invents a "
                 "price, a quote, a halt or a corporate action.")
    lines.append("")
    lines.append("## Timeframe summary")
    lines.append("")
    lines.append("| Timeframe | Rows | Symbols | Sessions | First date | Last date | Duplicate rows | Off-grid timestamps | Invalid bars |")
    lines.append("|---|---:|---:|---:|---|---|---:|---:|---:|")
    for tf, item in audit["timeframes"].items():
        if item.get("status") != "ok":
            lines.append(f"| {tf} | empty | | | | | | | |")
            continue
        lines.append(
            f"| {tf} | {_fmt(item['rows'])} | {_fmt(item['symbols'])} | "
            f"{_fmt(item['sessions'])} | {item['first_date']} | {item['last_date']} | "
            f"{_fmt(item['duplicates'])} | {_fmt(item['off_grid_timestamps'])} | "
            f"{_fmt(item['invalid_bar_rows'])} |"
        )
    lines.append("")
    lines.append("## Per-year rows and coverage")
    lines.append("")
    for tf, item in audit["timeframes"].items():
        if item.get("status") != "ok":
            continue
        lines.append(f"### {tf}")
        lines.append("")
        lines.append("| Year | Rows | Symbols | Sessions | Median symbol coverage | Symbols below 50% |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in item["per_year"]:
            cov = row.get("median_coverage")
            lines.append(
                f"| {int(row['year'])} | {_fmt(int(row['rows']))} | "
                f"{_fmt(int(row['symbols']))} | {_fmt(int(row['sessions']))} | "
                f"{_fmt(cov * 100.0 if cov is not None else None, 2)}% | "
                f"{_fmt(int(row['below_50pct_symbols']))} |"
            )
        lines.append("")
        lines.append("Coverage quantiles (bar count divided by the number of distinct "
                     "market timestamps in the same session):")
        lines.append("")
        lines.append("| Quantile | Coverage |")
        lines.append("|---|---:|")
        for q, value in item["coverage_quantiles"].items():
            lines.append(f"| {q} | {_fmt(value * 100.0 if value is not None else None, 2)}% |")
        lines.append("")
        lines.append(f"Symbols below 50% median coverage: {_fmt(item['symbols_below_50pct'])}. "
                     f"Symbols below 75%: {_fmt(item['symbols_below_75pct'])}.")
        lines.append("")

    lines.append("## Structural integrity")
    lines.append("")
    lines.append("| Timeframe | Invalid high | Invalid low | Nonpositive price | Negative volume | Zero volume | Non-regular rows | Large open gaps over 20% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for tf, item in audit["timeframes"].items():
        if item.get("status") != "ok":
            continue
        lines.append(
            f"| {tf} | {_fmt(item['invalid_high_rows'])} | {_fmt(item['invalid_low_rows'])} | "
            f"{_fmt(item['nonpositive_price_rows'])} | {_fmt(item['negative_volume_rows'])} | "
            f"{_fmt(item['zero_volume_rows'])} | {_fmt(item['non_regular_rows'])} | "
            f"{_fmt(item['large_open_gap_rows'])} |"
        )
    lines.append("")
    lines.append("## Gaps and corporate-action suspects")
    lines.append("")
    lines.append("Large gaps in an unadjusted archive can be splits, bonus shares, "
                 "rights issues or genuine news gaps. The archive has no corporate-action "
                 "file, so these rows are flagged, not adjusted. The pilot and the full "
                 "catalog use a conservative band-breaking screen rather than an invented "
                 "adjustment factor.")
    lines.append("")
    lines.append("| Timeframe | Symbol | Max open gap | Max close gap | Open gaps over 20% |")
    lines.append("|---|---|---:|---:|---:|")
    for tf, item in audit["timeframes"].items():
        if item.get("status") != "ok":
            continue
        for row in item["largest_gap_symbols"][:10]:
            lines.append(
                f"| {tf} | {row['symbol']} | {_fmt(row['max_open_gap'] * 100.0, 2)}% | "
                f"{_fmt(row['max_close_gap'] * 100.0, 2)}% | {_fmt(int(row['gap_20_count']))} |"
            )
    lines.append("")
    lines.append("## Timestamp convention")
    lines.append("")
    lines.append("The parquet `ts` column is epoch seconds in UTC. Karachi wall clock "
                 "is a fixed UTC+5. A 09:35 Karachi bar is stored as 04:35 UTC. The "
                 "research loader derives the session day, time of day and band end from "
                 "`ts` with the fixed offset and the repository's PSX session law; it "
                 "never uses the host timezone.")
    lines.append("")
    lines.append("## What this means for strategy eligibility")
    lines.append("")
    lines.append("- 2021 starts on 15 November and is partial. It is not a full year.")
    lines.append("- 2022 and 2023 have materially lower median coverage than 2024 to 2026.")
    lines.append("- Sparse symbols naturally generate fewer signals; they are not filled.")
    lines.append("- A strategy requiring continuous bars must filter on actual coverage, "
                 "not on the existence of a symbol in the current universe.")
    lines.append("- The locked test period starts on 1 July 2025. It is withheld from all "
                 "parameter selection.")
    lines.append("")
    text = "\n".join(lines) + "\n"
    for dash in DASHES:
        text = text.replace(dash, "-")
    return text
