/**
 * The header: what the exchange is doing, where the bars came from, and what
 * the connection is doing. Every fact here was resolved by the server, so
 * this component formats and never computes a session from the local clock.
 */

import type { FeedMeta, FeedState } from "../hooks/useChartFeed";
import { formatPrice, formatStamp } from "../chart/format";

export interface MarketHeaderProps {
  readonly meta: FeedMeta;
  readonly status: FeedState["status"];
  readonly error: FeedState["error"];
  readonly revisions: number;
  readonly bars: number;
}

const STATUS_LABEL: Record<string, string> = {
  loading: "loading history",
  connecting: "connecting",
  live: "live",
  reconnecting: "reconnecting",
  closed: "closed",
};

export function MarketHeader(props: MarketHeaderProps) {
  const { meta, status, error, revisions, bars } = props;
  const market = meta.market;
  const last = meta.payload?.bars.at(-1);
  const first = meta.payload?.bars.at(0);
  const change =
    last !== undefined && first !== undefined && first.o > 0
      ? ((last.c - first.o) / first.o) * 100
      : null;

  return (
    <header className="header">
      <div className="header__row">
        <h1 className="header__symbol">{meta.symbol || "no symbol"}</h1>
        <span className="header__price">
          {last !== undefined ? formatPrice(last.c) : "-"}
        </span>
        {change !== null ? (
          <span className={change >= 0 ? "delta delta--up" : "delta delta--down"}>
            {change >= 0 ? "+" : ""}
            {change.toFixed(2)}% session
          </span>
        ) : null}
        <span className={`pill pill--${status}`}>{STATUS_LABEL[status] ?? status}</span>
      </div>

      <div className="header__row header__row--facts">
        <span>
          {market === null
            ? "market: unknown"
            : `${market.phase} (${market.state})`}
        </span>
        <span>
          {market?.trading_day === true
            ? "trading day"
            : market === null
              ? ""
              : "not a trading day"}
        </span>
        {market?.band !== null && market?.band !== undefined ? (
          <span>
            band {market.band.open} to {market.band.close}
          </span>
        ) : null}
        {market?.next_event !== null && market?.next_event !== undefined ? (
          <span>
            next {market.next_event.event.toLowerCase()} at{" "}
            {formatStamp(market.next_event.at)}
          </span>
        ) : null}
        <span>{bars} bars</span>
        <span>{revisions} revised</span>
        {meta.source !== null ? (
          <span title={meta.source.note}>
            source {meta.source.label}
            {meta.source.delay_seconds > 0
              ? ` (delayed about ${Math.round(meta.source.delay_seconds / 60)} min)`
              : " (no delay reported)"}
          </span>
        ) : null}
      </div>

      {error !== null ? (
        <p className="header__error" role="status">
          {error.category}: {error.detail}
        </p>
      ) : null}
    </header>
  );
}
