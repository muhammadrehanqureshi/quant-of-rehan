/**
 * The status and provenance bar: what this chart is, and how much to trust it.
 *
 * Three rules shape it. It never claims live data from a healthy HTTP
 * response: a 200 says the service answered, and the age of the newest bar is
 * what says whether the market is moving. It shows the session's own facts
 * (which day, whether it is stored, which file answered) because a chart of
 * Friday read on a Sunday must say so. And it reports staleness as a measured
 * number of minutes, with a visible warning once a session in play is older
 * than the reader could reasonably assume.
 *
 * The staleness clock is the service's own `as_of`, not the browser's, so a
 * laptop in another timezone cannot change the reading (SO-8).
 */

import { useEffect, useState } from "react";

import type { MarketContext, Resolution } from "../api/types";
import type { FeedStatus } from "../hooks/useChartFeed";
import { formatClock, formatMinutes, formatStamp } from "../chart/format";
import { timeframeLabel } from "../chart/timeframes";

export interface StatusBarProps {
  readonly status: FeedStatus;
  readonly resolution: Resolution;
  /** The session facts the server resolved, never computed in the browser. */
  readonly market: MarketContext | null;
  readonly symbol: string;
  readonly day: string;
  readonly sessionNote: string;
  readonly archived: boolean;
  readonly captureName: string;
  readonly sha256: string;
  readonly bars: number;
  readonly gaps: number;
  readonly missingMinutes: number;
  readonly sourceLabel: string;
  readonly delaySeconds: number;
  /** The stamp of the newest bar in the series, which is what ages. */
  readonly lastBarAt: string;
  /** When the service answered. A healthy answer is not a fresh price. */
  readonly asOf: string;
  readonly volumeAvailable: boolean;
  readonly staleAfterMinutes: number;
  /** The venue's own cumulative order counter for this session, when it has one. */
  readonly ordersTotal: number | null;
  readonly error: { category: string; detail: string } | null;
  /** The expanded reading: the second detail line the toggle reveals. */
  readonly details: boolean;
}

const STATUS_TEXT: Record<FeedStatus, string> = {
  loading: "loading",
  connecting: "connecting",
  live: "live",
  reconnecting: "reconnecting",
  closed: "closed",
  snapshot: "finished session",
};

export function StatusBar(props: StatusBarProps) {
  const {
    status, resolution, market, symbol, day, sessionNote, archived,
    captureName, sha256, bars, gaps, missingMinutes, sourceLabel,
    delaySeconds, lastBarAt, asOf, volumeAvailable, staleAfterMinutes,
    ordersTotal, error, details,
  } = props;

  // A local tick so "2 min ago" keeps counting while a quiet session sits on
  // screen. It re-renders once a second, which is also what the bar's own
  // clock wants: the reading of now is the service's frame, not faith.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);

  // The age that matters is the age of the newest bar, not the age of the
  // answer: a service can reply in a millisecond about a price two hours old,
  // and calling that fresh is the mistake this whole bar exists to avoid.
  const ageMinutes = ageInMinutes(lastBarAt, now);
  const stale = ageMinutes !== null && ageMinutes >= staleAfterMinutes;

  return (
    <section className="status" aria-label="data status">
      <div className="status__row">
        <span className={`status__state status__state--${status}`}>
          {STATUS_TEXT[status]}
        </span>
        <span className="status__item">
          <span className="status__key">market</span>{" "}
          {market === null
            ? "unknown"
            : `${market.phase}${market.trading_day ? " · trading day" : " · not a trading day"}`}
        </span>
        {market?.band != null ? (
          <span className="status__item">
            <span className="status__key">band</span> {market.band.open} to{" "}
            {market.band.close}
          </span>
        ) : null}
        {market?.next_event != null ? (
          <span className="status__item">
            <span className="status__key">next</span>{" "}
            {market.next_event.event.toLowerCase()} at{" "}
            {formatStamp(market.next_event.at)}
          </span>
        ) : null}
        <span className="status__item">
          <span className="status__key">symbol</span> {symbol || "none"}
        </span>
        <span className="status__item">
          <span className="status__key">timeframe</span>{" "}
          {timeframeLabel(resolution)}
        </span>
        <span className="status__item">
          <span className="status__key">session</span> {day || "unknown"}
          {archived ? " (stored)" : ""}
        </span>
        <span className="status__item">
          <span className="status__key">bars</span> {bars}
        </span>
        {ordersTotal !== null ? (
          <span className="status__item" title="the venue's own cumulative order counter for this session">
            <span className="status__key">orders</span> {ordersTotal.toLocaleString("en-GB")}
          </span>
        ) : null}
        <span className="status__item">
          <span className="status__key">gaps</span> {gaps}
          {missingMinutes > 0 ? ` (${formatMinutes(missingMinutes)} missing)` : ""}
        </span>
        <span className={stale ? "status__item status__item--stale" : "status__item"}>
          <span className="status__key">newest bar</span>{" "}
          {lastBarAt.length > 0 ? formatClock(lastBarAt) : "none"}
          {ageMinutes !== null
            ? ` · ${formatMinutes(Math.max(0, Math.round(ageMinutes)))} ago`
            : ""}
        </span>
        <span className="status__item status__item--clock">
          {clockState(now)}{" "}UTC+5
        </span>
      </div>

      {stale ? (
        <p className="status__warning" role="status">
          The newest bar on this chart is {formatMinutes(Math.round(ageMinutes ?? 0))}{" "}
          old, so the last price shown is not a current one.
          {status === "live"
            ? " The stream is open, so the recorder may simply have nothing newer."
            : status === "snapshot"
              ? " This is a stored session and it will never update."
              : " Nothing is updating this chart right now."}
        </p>
      ) : null}

      {details ? (
        <div className="status__row status__row--provenance">
          <span className="status__item" title={sessionNote}>
            {sessionNote}
          </span>
          <span className="status__item" title={sourceLabel}>
            <span className="status__key">source</span> {sourceLabel || "unknown"}
            {delaySeconds > 0
              ? ` · ${Math.round(delaySeconds / 60)} min delayed`
              : " · no delay reported"}
          </span>
          <span className="status__item">
            <span className="status__key">volume</span>{" "}
            {volumeAvailable ? "reported" : "not reported"}
          </span>
          {captureName.length > 0 ? (
            <span className="status__item">
              <span className="status__key">file</span> {captureName}
              {sha256.length > 0 ? ` · sha256 ${sha256.slice(0, 12)}…` : ""}
            </span>
          ) : null}
          {asOf.length > 0 ? (
            <span className="status__item">
              <span className="status__key">service answered</span>{" "}
              {formatStamp(asOf)}
            </span>
          ) : null}
        </div>
      ) : null}

      {error !== null ? (
        <p className="status__error" role="status">
          {error.category}: {error.detail}
        </p>
      ) : null}
    </section>
  );
}

/** Minutes between a stamp and now, or null when the stamp is unusable. */
function ageInMinutes(stamp: string, now: number): number | null {
  const then = new Date(stamp).getTime();
  if (!Number.isFinite(then)) {
    return null;
  }
  return (now - then) / 60_000;
}

/** The reader's clock, on Karachi time, as a chart terminal shows it. */
function clockState(now: number): string {
  return new Date(now).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Karachi",
    hour12: false,
  });
}
