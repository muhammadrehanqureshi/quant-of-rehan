/**
 * One hook owns everything a chart needs from the network.
 *
 * It keeps the series in a ref, because the canvas reads it imperatively and
 * a new array per poll is exactly the waste this design avoids. What React
 * needs to re-render is the *metadata* (market state, session, notes,
 * provenance, status) and a version counter; the pixels are drawn from the ref.
 *
 * Two behaviours are deliberate:
 *
 *  * **A named session is a finished thing, so it is not streamed.** Asking
 *    for 2026-10-14 is a question with one answer, and opening a live stream
 *    for it would be an invitation to show a stale price as a moving one. The
 *    hook fetches it, labels the status "snapshot" and stops.
 *  * **A session span is one chart, not several.** With ``days`` above one
 *    the service merges the newest sessions into one payload, and the chart
 *    keeps reading it as the chart whose newest session happens to be live:
 *    the stream still moves it, but a stream snapshot only ever *adds or
 *    refreshes* bars (and the live market phase); it never deletes the stored
 *    days that preceded it, and it does not overwrite the merged answer's own
 *    session facts with one session's.
 *  * **A switch is a switch.** On a symbol, day or resolution change the
 *    series is cleared, the stream is torn down and the in-flight fetch is
 *    aborted before the next one starts, so one symbol's candles can never be
 *    drawn under another symbol's name.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, type ChartClient, type StreamState } from "../api/client";
import type {
  ChartPayload,
  ChartSession,
  ErrorCategory,
  Gap,
  Resolution,
  SourceInfo,
} from "../api/types";
import { ColumnSeries } from "../chart/series";

export interface FeedMeta {
  readonly symbol: string;
  readonly resolution: string;
  readonly market: ChartPayload["market"] | null;
  readonly session: ChartSession | null;
  readonly source: SourceInfo | null;
  readonly notes: readonly string[];
  readonly gaps: readonly Gap[];
  readonly payload: ChartPayload | null;
}

/** The status the UI shows. "snapshot" is a finished session, not a stream. */
export type FeedStatus = StreamState | "loading" | "snapshot";

export interface FeedState {
  readonly series: ColumnSeries;
  readonly meta: FeedMeta;
  readonly status: FeedStatus;
  readonly error: { category: ErrorCategory; detail: string } | null;
  readonly version: number;
  readonly refresh: () => void;
}

const EMPTY_META: FeedMeta = {
  symbol: "",
  resolution: "",
  market: null,
  session: null,
  source: null,
  notes: [],
  gaps: [],
  payload: null,
};

export function useChartFeed(
  client: ChartClient,
  symbol: string,
  resolution: Resolution,
  options: { day?: string; days?: number | undefined; limit?: number } = {},
): FeedState {
  const day = options.day ?? "";
  const days = Math.max(0, Math.floor(options.days ?? 0));
  // A merge of one day is no merge: that is the ordinary live chart.
  const merged = days > 1 && day.length === 0;
  const limit = options.limit ?? 2000;
  const series = useMemo(() => new ColumnSeries(limit), [limit]);
  const [meta, setMeta] = useState<FeedMeta>(EMPTY_META);
  const [status, setStatus] = useState<FeedStatus>("loading");
  const [error, setError] = useState<FeedState["error"]>(null);
  const [version, setVersion] = useState(0);
  const [manual, setManual] = useState(0);

  const bump = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    if (symbol.length === 0) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    series.clear();
    setMeta(EMPTY_META);
    setStatus("loading");
    setError(null);
    bump();

    const adopt = (payload: ChartPayload, spanFacts = false) => {
      series.upsertMany(payload.bars);
      setMeta((current) => {
        if (!spanFacts || current.payload === null) {
          return {
            symbol: payload.symbol,
            resolution: payload.resolution,
            market: payload.market,
            session: payload.session,
            source: payload.source,
            notes: payload.notes,
            gaps: payload.gaps,
            payload,
          };
        }
        // A span's identity is the merged answer: which sessions it spans,
        // how they are stored, what is missing between them. A live snapshot
        // refreshes the bars and the market phase under that identity and
        // replaces nothing about it.
        return {
          ...current,
          market: payload.market,
          payload: { ...payload, bar_count: current.payload.bar_count },
        };
      });
      bump();
    };

    void client
      .bars(symbol, resolution, {
        limit,
        day,
        days: merged ? days : undefined,
        signal: controller.signal,
      })
      .then((payload) => {
        if (!cancelled) {
          adopt(payload);
          // A live chart's status belongs to the stream, which reports it as
          // it happens. Only a named session states its own, because nothing
          // is going to update it.
          if (day.length > 0) {
            setStatus("snapshot");
          }
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setError(categoryOf(failure));
          if (day.length > 0) {
            setStatus("snapshot");
          } else {
            setStatus("closed");
          }
        }
      });

    if (day.length > 0) {
      // A finished session does not move. No stream, and nothing to clean up
      // beyond the aborted fetch.
      return () => {
        cancelled = true;
        controller.abort();
        series.clear();
      };
    }

    const handle = client.stream(symbol, resolution, {
      onSnapshot: (payload) => {
        if (!cancelled) {
          adopt(payload, merged);
        }
      },
      onBars: (event) => {
        if (cancelled) {
          return;
        }
        series.upsertMany(event.bars);
        bump();
      },
      onState: (state, detail) => {
        if (cancelled) {
          return;
        }
        setStatus(state);
        setError(
          state === "reconnecting" && detail !== undefined
            ? { category: "NETWORK", detail }
            : null,
        );
      },
    });

    return () => {
      cancelled = true;
      controller.abort();
      handle.close();
      series.clear();
    };
  }, [client, symbol, resolution, limit, day, days, series, bump, manual]);

  const refresh = useCallback(() => setManual((value) => value + 1), []);

  return { series, meta, status, error, version, refresh };
}

function categoryOf(error: unknown): { category: ErrorCategory; detail: string } {
  if (error instanceof ApiError) {
    return { category: error.category, detail: error.detail };
  }
  if (error instanceof Error) {
    return { category: "INTERNAL", detail: error.message };
  }
  return { category: "INTERNAL", detail: String(error) };
}
