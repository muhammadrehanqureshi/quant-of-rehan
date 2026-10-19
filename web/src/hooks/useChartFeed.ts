/**
 * One hook owns everything a chart needs from the network.
 *
 * It keeps the series in a ref, because the canvas reads it imperatively and
 * a new array per poll is exactly the waste this design avoids. What React
 * needs to re-render is the *metadata* (market state, notes, provenance,
 * status) and a version counter; the pixels are drawn from the ref.
 *
 * Failure handling is deliberately visible: the hook exposes a status and a
 * named error, and it never leaves one symbol's bars on screen while the
 * next symbol is loading. On a symbol or resolution change it clears the
 * series, tears down the stream and aborts the in-flight fetch before
 * starting the next one.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, type ChartClient, type StreamHandle, type StreamState } from "../api/client";
import type { ChartPayload, ErrorCategory, Gap, LiveQuote, SourceInfo } from "../api/types";
import { formatStamp } from "../chart/format";
import { ColumnSeries } from "../chart/series";

export interface FeedMeta {
  readonly symbol: string;
  readonly resolution: string;
  readonly market: ChartPayload["market"] | null;
  readonly source: SourceInfo | null;
  readonly notes: readonly string[];
  readonly gaps: readonly Gap[];
  readonly payload: ChartPayload | null;
  readonly liveQuote: LiveQuote | null;
  readonly quoteStatus: StreamState | "loading";
  readonly quoteError: string | null;
}

export interface FeedState {
  readonly series: ColumnSeries;
  readonly meta: FeedMeta;
  readonly status: StreamState | "loading";
  readonly error: { category: ErrorCategory; detail: string } | null;
  readonly version: number;
  readonly refresh: () => void;
  readonly refreshQuote: () => void;
}

const EMPTY_META: FeedMeta = {
  symbol: "",
  resolution: "",
  market: null,
  source: null,
  notes: [],
  gaps: [],
  payload: null,
  liveQuote: null,
  quoteStatus: "loading",
  quoteError: null,
};

export function useChartFeed(
  client: ChartClient,
  symbol: string,
  resolution: "1m" | "1d" | "session",
  limit = 2000,
): FeedState {
  const series = useMemo(() => new ColumnSeries(limit), [limit]);
  const [meta, setMeta] = useState<FeedMeta>(EMPTY_META);
  const [status, setStatus] = useState<StreamState | "loading">("loading");
  const [error, setError] = useState<FeedState["error"]>(null);
  const [version, setVersion] = useState(0);
  const [manual, setManual] = useState(0);
  const [quoteRefresh, setQuoteRefresh] = useState(0);
  const [liveQuote, setLiveQuote] = useState<LiveQuote | null>(null);
  const [quoteStatus, setQuoteStatus] = useState<StreamState | "loading">("loading");
  const [quoteError, setQuoteError] = useState<string | null>(null);

  const bump = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    if (symbol.length === 0) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    // A switch is a switch: nothing from the previous symbol survives it.
    series.clear();
    setMeta(EMPTY_META);
    setStatus("loading");
    setError(null);
    bump();

    const adopt = (payload: ChartPayload) => {
      series.upsertMany(payload.bars);
      setMeta({
        symbol: payload.symbol,
        resolution: payload.resolution,
        market: payload.market,
        source: payload.source,
        notes: payload.notes,
        gaps: payload.gaps,
        payload,
        liveQuote: null,
        quoteStatus: "loading",
        quoteError: null,
      });
      bump();
    };

    client
      .bars(symbol, resolution, { limit, signal: controller.signal })
      .then((payload) => {
        if (!cancelled) {
          adopt(payload);
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          // The stream may still be healthy; it reports its own state. This
          // error explains why the initial history is missing.
          setError(categoryOf(failure));
        }
      });

    const handle = client.stream(symbol, resolution, {
      onSnapshot: (payload) => {
        if (!cancelled) {
          adopt(payload);
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
  }, [client, symbol, resolution, limit, series, bump, manual]);

  useEffect(() => {
    setLiveQuote(null);
    setQuoteStatus("loading");
    setQuoteError(null);
    if (symbol.length === 0) return;
    let cancelled = false;
    let stream: StreamHandle | null = null;
    const controller = new AbortController();
    const adopt = (quote: LiveQuote) => {
      if (cancelled) return;
      setLiveQuote((current) => current === null ||
        Date.parse(quote.observed_at) >= Date.parse(current.observed_at)
        ? quote : current);
    };
    client.liveQuote(symbol, controller.signal)
      .then(adopt)
      .catch((failure: unknown) => {
        if (!cancelled) setQuoteError(categoryOf(failure).detail);
      });
    stream = client.streamLiveQuote(symbol, {
      onQuote: adopt,
      onState: (state, detail) => {
        if (cancelled) return;
        setQuoteStatus(state);
        if (state === "reconnecting" && detail !== undefined) {
          setQuoteError(detail);
        } else if (state === "live") {
          setQuoteError(null);
        }
      },
    });
    return () => {
      cancelled = true;
      controller.abort();
      stream?.close();
    };
  }, [client, symbol, quoteRefresh]);

  const refresh = useCallback(() => setManual((value) => value + 1), []);
  const refreshQuote = useCallback(() => setQuoteRefresh((value) => value + 1), []);
  const currentQuote = liveQuote?.symbol === symbol ? liveQuote : null;
  const currentMeta = meta.symbol === symbol && meta.resolution === resolution
    ? meta : EMPTY_META;
  const liveNotes = currentQuote === null ? currentMeta.notes : [
    ...currentMeta.notes,
    `last broker quote ${formatStamp(currentQuote.observed_at)} PKT` +
      (currentQuote.fresh ? "" : ` is stale (${currentQuote.age_seconds}s old)`),
  ];

  return {
    series,
    meta: {
      ...currentMeta,
      liveQuote: currentQuote,
      quoteStatus,
      quoteError,
      notes: liveNotes,
    },
    status,
    error,
    version,
    refresh,
    refreshQuote,
  };
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
