/**
 * The screener: every symbol the tape watched this session, one sortable
 * table, the way TradingView's own screener reads.
 *
 * It filters and sorts; it never invents a fact. Every column is a measured
 * value from the catalogue - the session's last close, its change against
 * the session's own open, the summed volume, the bar count - and a symbol
 * with no bars says so rather than showing a zero. Clicking a row opens that
 * symbol on the chart behind the panel.
 */

import { useMemo, useState } from "react";

import type { SymbolRow } from "../api/types";
import { formatPrice, formatVolume } from "../chart/format";

export type ScreenerSort =
  | "symbol"
  | "change"
  | "volume"
  | "bars"
  | "price";

export interface ScreenerProps {
  readonly rows: readonly SymbolRow[];
  readonly loading: boolean;
  /** The stored session being read, or "" for the live one. */
  readonly day: string;
  readonly onSymbol: (symbol: string) => void;
  readonly onClose: () => void;
}

interface Screened {
  readonly row: SymbolRow;
  readonly change: number | null;
  readonly percent: number | null;
}

/** The session's own change, measured exactly as the watchlist measures it. */
export function screenerChange(
  row: SymbolRow,
): { change: number; percent: number } | null {
  if (row.close == null || row.open == null || row.open === 0) {
    return null;
  }
  const change = row.close - row.open;
  return { change, percent: change / row.open * 100 };
}

/**
 * The table's sort, kept pure so it can be read and tested without a browser.
 * A symbol without the sorted fact sorts last under any direction: an absence
 * is not a small number.
 */
export function sortScreened(
  rows: readonly Screened[],
  sort: ScreenerSort,
  descending: boolean,
): Screened[] {
  const value = (item: Screened): number | string => {
    switch (sort) {
      case "symbol": return item.row.symbol;
      case "price": return item.row.close ?? Number.NaN;
      case "volume": return item.row.volume ?? Number.NaN;
      case "bars": return item.row.bars ?? Number.NaN;
      case "change": return item.change ?? Number.NaN;
    }
  };
  const copy = [...rows];
  copy.sort((a, b) => {
    const left = value(a);
    const right = value(b);
    const leftMissing = typeof left === "number" && !Number.isFinite(left);
    const rightMissing = typeof right === "number" && !Number.isFinite(right);
    if (leftMissing || rightMissing) {
      return leftMissing === rightMissing ? 0 : leftMissing ? 1 : -1;
    }
    if (typeof left === "string" || typeof right === "string") {
      const order = String(left).localeCompare(String(right));
      return descending ? -order : order;
    }
    const order = left < right ? -1 : left > right ? 1 : 0;
    return descending ? -order : order;
  });
  return copy;
}

export function filterScreened(
  rows: readonly Screened[],
  query: string,
  tradedOnly: boolean,
): Screened[] {
  const needle = query.trim().toUpperCase();
  return rows.filter((item) => {
    if (tradedOnly && (item.row.bars ?? 0) === 0) {
      return false;
    }
    return needle.length === 0 || item.row.symbol.includes(needle);
  });
}

export function Screener(props: ScreenerProps) {
  const { rows, loading, day, onSymbol, onClose } = props;
  const [query, setQuery] = useState("");
  const [tradedOnly, setTradedOnly] = useState(true);
  const [sort, setSort] = useState<ScreenerSort>("change");
  const [descending, setDescending] = useState(true);

  const screened = useMemo(() => rows.map((row) => {
    const measured = screenerChange(row);
    return {
      row,
      change: measured === null ? null : measured.change,
      percent: measured === null ? null : measured.percent,
    };
  }), [rows]);

  const shown = useMemo(
    () => sortScreened(filterScreened(screened, query, tradedOnly),
      sort, descending),
    [screened, query, tradedOnly, sort, descending],
  );

  const traded = screened.filter((item) => (item.row.bars ?? 0) > 0).length;
  const advancing = screened.filter((item) => (item.percent ?? 0) > 0).length;
  const declining = screened.filter((item) => (item.percent ?? 0) < 0).length;

  const head = (key: ScreenerSort, label: string, numeric = true) => (
    <th
      scope="col"
      className={numeric ? "screener__th screener__th--num"
        : "screener__th"}
      aria-sort={sort === key
        ? descending ? "descending" : "ascending"
        : "none"}
    >
      <button
        type="button"
        className="screener__sort"
        onClick={() => {
          if (sort === key) {
            setDescending((current) => !current);
          } else {
            setSort(key);
            setDescending(key !== "symbol");
          }
        }}
        title={`sort by ${label}`}
      >
        {label}
        {sort === key ? <span aria-hidden="true">
          {descending ? " ▾" : " ▴"}
        </span> : null}
      </button>
    </th>
  );

  return (
    <section className="screener" aria-label="stock screener">
      <header className="screener__head">
        <h2 className="screener__title">Screener</h2>
        <span className="screener__facts">
          {loading
            ? "reading the catalogue…"
            : `${traded} traded · ${advancing} up · ${declining} down`}
        </span>
        <input
          type="search"
          className="screener__search"
          placeholder="filter symbols"
          aria-label="filter symbols"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <label className="screener__toggle">
          <input
            type="checkbox"
            checked={tradedOnly}
            onChange={(event) => setTradedOnly(event.target.checked)}
          />
          traded only
        </label>
        <span className="screener__count">{shown.length} rows</span>
        <button type="button" className="screener__close" onClick={onClose}>
          close
        </button>
      </header>

      <div className="screener__body">
        <table className="screener__table">
          <thead>
            <tr>
              {head("symbol", "Symbol", false)}
              {head("price", "Last")}
              {head("change", "Chg")}
              {head("change", "Chg%")}
              {head("volume", "Volume")}
              {head("bars", "Bars")}
              <th scope="col" className="screener__th screener__th--num">
                Range
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 ? (
              <tr>
                <td colSpan={7} className="screener__quiet">
                  {loading
                    ? "waiting for the catalogue…"
                    : "no symbol matches this filter in this session."}
                </td>
              </tr>
            ) : shown.map((item) => {
              const row = item.row;
              const up = (item.percent ?? 0) > 0;
              const down = (item.percent ?? 0) < 0;
              const tone = up ? " screener__cell--up"
                : down ? " screener__cell--down" : "";
              const low = row.low ?? null;
              const high = row.high ?? null;
              const close = row.close ?? null;
              return (
                <tr
                  key={row.symbol}
                  className="screener__row"
                  onClick={() => onSymbol(row.symbol)}
                >
                  <th scope="row" className="screener__cell screener__cell--symb">
                    <button
                      type="button"
                      className="screener__open"
                      title={`open ${row.symbol} on the chart`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onSymbol(row.symbol);
                      }}
                    >
                      {row.symbol}
                    </button>
                    {row.index === true
                      ? <span className="row__badge">index</span>
                      : null}
                  </th>
                  <td className="screener__cell screener__cell--num">
                    {close === null
                      ? <span className="wrow__absent">no price</span>
                      : formatPrice(close)}
                  </td>
                  <td className={`screener__cell screener__cell--num${tone}`}>
                    {item.change === null ? "-" : item.change.toFixed(2)}
                  </td>
                  <td className={`screener__cell screener__cell--num${tone}`}>
                    {item.percent === null
                      ? "-"
                      : `${item.percent >= 0 ? "+" : ""}${item.percent.toFixed(2)}%`}
                  </td>
                  <td className="screener__cell screener__cell--num">
                    {row.volume == null
                      ? <span className="wrow__absent">-</span>
                      : formatVolume(row.volume)}
                  </td>
                  <td className="screener__cell screener__cell--num">
                    {(row.bars ?? 0) === 0
                      ? <span className="wrow__absent">no bars</span>
                      : row.bars}
                  </td>
                  <td className="screener__cell screener__cell--num screener__cell--range">
                    {low === null || high === null || close === null
                      ? <span className="wrow__absent">-</span>
                      : `${formatPrice(low)} - ${formatPrice(high)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="screener__foot">
        {day.length > 0
          ? `facts are the stored session ${day}`
          : "facts are this live session"}{" "}
        · change is measured against the session's own open · click a row to
        chart it
      </footer>
    </section>
  );
}
