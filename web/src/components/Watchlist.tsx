/**
 * The watchlist, on the right, the way a chart terminal has it.
 *
 * It holds exactly the symbols the reader put on it - nothing more - and
 * every column is measured, not invented: the last price is the session's
 * last close, the change is against the session's first print, the volume
 * is the session's summed tape. A symbol without bars in this session says
 * "no bars" instead of a blank or a zero.
 *
 * The list persists in localStorage, so a reload is no cardoso of work.
 */

import { useMemo } from "react";

import type { SymbolRow } from "../api/types";
import { formatClock, formatPrice } from "../chart/format";
import { SymbolSearch } from "./SymbolSearch";

export interface WatchlistProps {
  readonly rows: readonly SymbolRow[];
  /** The user's own symbols, in their order. */
  readonly watch: readonly string[];
  readonly symbol: string;
  readonly day: string;
  readonly loading: boolean;
  readonly onSymbol: (symbol: string) => void;
  readonly onWatchChange: (next: readonly string[]) => void;
  /** The quick-add dialog is owned by the parent so the toolbar shares it. */
  readonly searchOpen: boolean;
  readonly onSearchOpen: () => void;
  readonly onSearchClose: () => void;
}

/** The change of the session so far, measured against its first print. */
export function sessionChange(
  row: SymbolRow | undefined,
): { change: number; percent: number } | null {
  if (row === undefined || row.close == null || row.open == null
      || row.open === 0) {
    return null;
  }
  const change = row.close - row.open;
  return { change, percent: change / row.open * 100 };
}

export function Watchlist(props: WatchlistProps) {
  const {
    rows, watch, symbol, day, loading, onSymbol, onWatchChange,
    searchOpen, onSearchOpen, onSearchClose,
  } = props;
  const bySymbol = useMemo(() => {
    const map = new Map<string, SymbolRow>();
    for (const row of rows) {
      map.set(row.symbol, row);
    }
    return map;
  }, [rows]);

  const traded = rows.filter((row) => (row.bars ?? 0) > 0).length;
  const detail = bySymbol.get(symbol);
  const detailChange = sessionChange(detail);

  const remove = (name: string) => {
    onWatchChange(watch.filter((item) => item !== name));
  };

  return (
    <div className="watchpane">
      <SymbolSearch
        open={searchOpen}
        rows={rows}
        loading={loading}
        action="add"
        onPick={onSymbol}
        onClose={onSearchClose}
      />

      <section className="watchlist" aria-label="watchlist">
        <header className="watchlist__head">
          <span className="watchlist__title">Watchlist</span>
          <button type="button" className="watchlist__add"
                  aria-label="add symbol to the watchlist"
                  title="Add a symbol"
                  onClick={onSearchOpen}>
            +
          </button>
        </header>
        <p className="watchlist__count">
          {rows.length === 0
            ? "no catalogue"
            : `${traded} of ${rows.length} traded this session`}
        </p>

        <table className="watchlist__table">
          <thead>
            <tr>
              <th scope="col" className="watchlist__th watchlist__th--symb">Symb</th>
              <th scope="col" className="watchlist__th">Last</th>
              <th scope="col" className="watchlist__th">Chg</th>
              <th scope="col" className="watchlist__th">Chg%</th>
              <th scope="col" className="watchlist__th watchlist__th--vol">Vol</th>
            </tr>
          </thead>
          <tbody>
            {watch.length === 0 ? (
              <tr>
                <td colSpan={5} className="watchlist__quiet">
                  {loading
                    ? "reading the catalogue…"
                    : "Your list is empty. Use + to put symbols on it."}
                </td>
              </tr>
            ) : watch.map((name) => {
              const row = bySymbol.get(name);
              const change = sessionChange(row);
              const active = name === symbol;
              const bars = row?.bars ?? 0;
              const volume = row?.volume ?? null;
              return (
                <tr key={name} className={active ? "wrow wrow--active" : "wrow"}
                    aria-current={active ? "true" : undefined}>
                  <td className="wrow__cell wrow__cell--symb">
                    <button
                      type="button"
                      className="wrow__open"
                      onClick={() => onSymbol(name)}
                      title={`open ${name}`}
                    >
                      {name}
                      {row?.index === true
                        ? <span className="row__badge">index</span>
                        : null}
                    </button>
                    <button
                      type="button"
                      className="wrow__remove"
                      aria-label={`remove ${name} from the watchlist`}
                      title={`remove ${name}`}
                      onClick={() => remove(name)}
                    >
                      ✕
                    </button>
                  </td>
                  <td className="wrow__cell">
                    {row?.close === null || row === undefined
                      ? <span className="wrow__absent">
                          {loading ? "…" : bars > 0 ? "no price" : "no bars"}
                        </span>
                      : formatPrice(row.close)}
                  </td>
                  <td className={"wrow__cell" + (change && change.change < 0
                    ? " wrow__cell--down"
                    : change ? " wrow__cell--up" : "")}>
                    {change === null
                      ? "-"
                      : change.change.toFixed(2)}
                  </td>
                  <td className={"wrow__cell" + (change && change.percent < 0
                    ? " wrow__cell--down"
                    : change ? " wrow__cell--up" : "")}>
                    {change === null
                      ? "-"
                      : change.percent.toFixed(2)}
                  </td>
                  <td className="wrow__cell wrow__cell--vol">
                    {volume === null
                      ? <span className="wrow__absent">-</span>
                      : volume.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="watchlist__note">
          {day.length > 0
            ? `facts are this stored session (${day});`
            : "facts are this live session,"}{" "}
          measured against its own first print.
        </p>
      </section>

      <section className="detail" aria-label="symbol detail">
        {detail === undefined ? null : (
          <>
            <div className="detail__who">
              <span className="detail__symbol">{detail.symbol}</span>
              <span className="detail__market">PSX</span>
            </div>
            <p className="detail__price">
              {detail.close === null
                ? <span className="detail__absent">no price this session</span>
                : formatPrice(detail.close)}
              {detailChange !== null && detail.close !== null ? (
                <span className={detailChange.change < 0
                  ? "detail__chg detail__chg--down"
                  : "detail__chg detail__chg--up"}>
                  {" "}{detailChange.change.toFixed(2)}{" "}
                  ({detailChange.percent.toFixed(2)}%)
                </span>
              ) : null}
            </p>
            <p className="detail__row">
              {detail.bars ?? 0} bars
              {detail.first !== null
                ? ` · from ${formatClock(detail.first)}`
                : ""}
              {detail.last !== null
                ? ` to ${formatClock(detail.last)}`
                : ""}
            </p>
            {typeof detail.high === "number" && typeof detail.low === "number"
              && detail.close !== null
              ? (
                <div className="detail__range">
                  <span className="detail__rangelow">{formatPrice(detail.low)}</span>
                  <span className="detail__rangebar" aria-hidden="true">
                    <span className="detail__rangepoint" style={{
                      left: `${Math.min(100, Math.max(0,
                        (detail.close - detail.low)
                        / Math.max(1e-9, detail.high - detail.low) * 100))}%`,
                    }} />
                  </span>
                  <span className="detail__rangehigh">{formatPrice(detail.high)}</span>
                </div>
              )
              : null}
          </>
        )}
      </section>
    </div>
  );
}
