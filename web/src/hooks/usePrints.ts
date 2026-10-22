/**
 * One polling hook for the order-print ledger.
 *
 * The bars stream is push; the prints ledger is polled, because the server
 * rebuilds it from a growing capture file and a poll at the minute grain is
 * exactly what the tape itself observes anyway. The refetch never cries
 * wolf: a source without a ledger answers an empty report with a note, so a
 * missing feature stays quiet instead of turning into an error state.
 */

import { useEffect, useRef, useState } from "react";

import type { ChartClient } from "../api/client.js";
import type { PrintReport } from "../api/types.js";

export interface PrintsState {
  /** The latest ledger, or null before the first answer. */
  readonly report: PrintReport | null;
  /** Human failure from the last poll, cleared on the next good answer. */
  readonly error: string | null;
}

/**
 * Poll `/api/prints` for one symbol on a fixed cadence.
 *
 * `enabled` stays false while the chart is replaying an archive or the
 * anchor is the summary strip, because those draws read history, not the
 * live tape, and a ledger poll on top of them is only noise.
 */
export function usePrints(
  client: ChartClient,
  symbol: string,
  day: string,
  enabled: boolean,
  intervalMs = 5000,
): PrintsState {
  const [report, setReport] = useState<PrintReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The latest started poll wins: a slow answer never overwrites a newer one.
  const runRef = useRef(0);

  useEffect(() => {
    if (!enabled || symbol.length === 0) {
      setReport(null);
      setError(null);
      return;
    }
    runRef.current += 1;
    const run = runRef.current;
    let cancelled = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async (): Promise<void> => {
      try {
        const next = await client.prints(symbol, day, controller.signal);
        if (cancelled || runRef.current !== run) {
          return;
        }
        setReport(next);
        setError(null);
      } catch (caught) {
        if (cancelled || runRef.current !== run || controller.signal.aborted) {
          return;
        }
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (!cancelled && runRef.current === run) {
          timer = setTimeout(poll, intervalMs);
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [client, symbol, day, enabled, intervalMs]);

  return { report, error };
}
