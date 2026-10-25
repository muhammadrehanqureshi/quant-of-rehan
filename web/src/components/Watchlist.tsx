/**
 * The watchlist, on the right, the way TradingView's panel reads.
 *
 * Three numbers and a name per row, right aligned and tabular, in a list
 * that is nothing but rows: no grid lines, no badges shouting, no second
 * header. The row you are charting is the one that sits in a lighter plate
 * with a teal edge, so the eye finds it without reading. Removing a symbol
 * is the small x that appears when the pointer is on its row (and on
 * keyboard focus), not furniture on every line.
 *
 * Under the list, the detail card: the symbol's own last price, its change
 * against the session's first print, the session range and the traded
 * volume, exactly the facts the tape carries and no others.
 */

import { useMemo } from "react";

import type { SymbolRow } from "../api/types";
import { formatClock, formatPrice, formatVolume } from "../chart/format";
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

function tone(percent: number | null | undefined): string {
  if (percent === null || percent === undefined || percent === 0) {
    return "";
  }
  return percent > 0 ? " wrow__cell--up" : " wrow__cell--down";
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
          <h2 className="watchlist__title">Watchlist</h2>
          <div className="watchlist__tools">
            <button
              type="button"
              className="watchlist__tool"
              aria-label="search the catalogue"
              title="Search the catalogue"
              onClick={onSearchOpen}
            >
              ⌕
            </button>
            <button
              type="button"
              className="watchlist__tool"
              aria-label="add symbol to the watchlist"
              title="Add a symbol"
              onClick={onSearchOpen}
            >
              +
            </button>
          </div>
        </header>
        <p className="watchlist__count">
          {rows.length === 0
            ? "no catalogue"
            : `${traded} of ${rows.length} traded this session`}
        </p>

        <div className="watchlist__body">
          <table className="watchlist__table">
            <thead>
              <tr>
                <th scope="col" className="watchlist__th watchlist__th--symb">
                  Symbol
                </th>
                <th scope="col" className="watchlist__th">Last</th>
                <th scope="col" className="watchlist__th">Chg</th>
                <th scope="col" className="watchlist__th">Chg%</th>
              </tr>
            </thead>
            <tbody>
              {watch.length === 0 ? (
                <tr>
                  <td colSpan={4} className="watchlist__quiet">
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
                const own = tone(change?.percent);
                return (
                  <tr
                    key={name}
                    className={active ? "wrow wrow--active" : "wrow"}
                    aria-current={active ? "true" : undefined}
                    onClick={() => onSymbol(name)}
                  >
                    <th scope="row" className="wrow__cell wrow__cell--symb">
                      <button
                        type="button"
                        className="wrow__open"
                        onClick={(event) => {
                          event.stopPropagation();
                          onSymbol(name);
                        }}
                        title={`open ${name} on the chart`}
                      >
                        {name}
                      </button>
                      {row?.index === true
                        ? <span className="wrow__tag">IDX</span>
                        : null}
                      <button
                        type="button"
                        className="wrow__remove"
                        aria-label={`remove ${name} from the watchlist`}
                        title={`remove ${name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          remove(name);
                        }}
                      >
                        ✕
                      </button>
                    </th>
                    <td className="wrow__cell">
                      {row?.close === null || row === undefined
                        ? <span className="wrow__absent">
                            {loading ? "…" : bars > 0 ? "no price" : "no bars"}
                          </span>
                        : formatPrice(row.close)}
                    </td>
                    <td className={"wrow__cell" + own}>
                      {change === null ? "-" : change.change.toFixed(2)}
                    </td>
                    <td className={"wrow__cell" + own}>
                      {change === null
                        ? "-"
                        : `${change.percent >= 0 ? "+" : ""}` +
                          `${change.percent.toFixed(2)}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="watchlist__note">
          {day.length > 0
            ? `facts are this stored session (${day});`
            : "facts are this live session,"}{" "}
          measured against its own first print.
        </p>
      </section>

      <section className="detail" aria-label="symbol detail">
        {detail === undefined ? (
          <p className="detail__quiet">
            {symbol.length === 0
              ? "no symbol chosen"
              : `${symbol} has no row in this session's catalogue`}
          </p>
        ) : (
          <>
            <div className="detail__who">
              <span className="detail__symbol">{detail.symbol}</span>
              <span className="detail__market">
                {detail.index === true ? "INDEX · PSX" : "PSX"}
              </span>
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
                  ({detailChange.percent >= 0 ? "+" : ""}
                  {detailChange.percent.toFixed(2)}%)
                </span>
              ) : null}
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
            <dl className="detail__stats">
              <div>
                <dt>volume</dt>
                <dd>{detail.volume == null
                  ? "-" : formatVolume(detail.volume)}</dd>
              </div>
              <div>
                <dt>bars</dt>
                <dd>{detail.bars ?? 0}</dd>
              </div>
              <div>
                <dt>first</dt>
                <dd>{detail.first === null ? "-" : formatClock(detail.first)}</dd>
              </div>
              <div>
                <dt>last</dt>
                <dd>{detail.last === null ? "-" : formatClock(detail.last)}</dd>
              </div>
            </dl>
          </>
        )}
      </section>
    </div>
  );
}
