/**
 * The application shell.
 *
 * It holds only what a human is choosing (the symbol and the resolution) and
 * what the service says about itself (the catalogue and the offered
 * resolutions). The series, the stream and the notes belong to the feed
 * hook; the pixels belong to the canvas.
 */

import { useEffect, useMemo, useState } from "react";

import { ApiError, ChartClient } from "./api/client";
import { type Resolution, parseHealth } from "./api/types";
import { ChartCanvas } from "./components/ChartCanvas";
import { MarketHeader } from "./components/MarketHeader";
import { NotesPanel } from "./components/NotesPanel";
import { SymbolPicker } from "./components/SymbolPicker";
import { useChartFeed } from "./hooks/useChartFeed";

const FALLBACK_RESOLUTIONS: readonly Resolution[] = ["1m"];

function initialSymbol(): string {
  const hash = window.location.hash.replace(/^#/, "").trim().toUpperCase();
  return hash.length > 0 ? hash : "";
}

export function App() {
  const client = useMemo(() => new ChartClient(), []);
  const [symbol, setSymbol] = useState(initialSymbol);
  const [resolution, setResolution] = useState<Resolution>("1m");
  const [catalogue, setCatalogue] = useState<readonly string[]>([]);
  const [resolutions, setResolutions] =
    useState<readonly Resolution[]>(FALLBACK_RESOLUTIONS);
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .health()
      .then((raw) => {
        if (cancelled) {
          return;
        }
        try {
          const health = parseHealth(raw);
          setResolutions(
            health.resolutions.length > 0
              ? health.resolutions
              : FALLBACK_RESOLUTIONS,
          );
          if (!health.resolutions.includes(resolution)) {
            setResolution(health.resolutions[0] ?? "1m");
          }
        } catch (error) {
          setBootError(error instanceof Error ? error.message : String(error));
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBootError(
            error instanceof ApiError
              ? `${error.category}: ${error.detail}`
              : String(error),
          );
        }
      });
    client
      .symbols()
      .then((items) => {
        if (!cancelled) {
          setCatalogue(items);
          setSymbol((current) => (current.length > 0 ? current : items[0] ?? ""));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // The catalogue and the offered resolutions are read once per mount; the
    // current resolution is read from the state the effect closes over.
  }, [client]);

  const feed = useChartFeed(client, symbol, resolution);
  const bars = feed.meta.payload?.bar_count ?? feed.series.length;

  return (
    <div className="app">
      <MarketHeader
        meta={feed.meta}
        status={feed.status}
        error={feed.error ?? (bootError === null ? null : {
          category: "INTERNAL",
          detail: bootError,
        })}
        revisions={feed.series.revisionCount}
        bars={bars}
        onRefreshQuote={feed.refreshQuote}
      />
      <div className="app__controls">
        <SymbolPicker
          symbol={symbol}
          onSymbol={(next) => {
            setSymbol(next);
            window.location.hash = next;
          }}
          catalogue={catalogue}
          resolution={resolution}
          onResolution={setResolution}
          resolutions={resolutions}
        />
        <button type="button" onClick={feed.refresh}>
          reload history
        </button>
      </div>
      <ChartCanvas
        series={feed.series}
        gaps={feed.meta.gaps}
        version={feed.version}
      />
      <NotesPanel meta={feed.meta} />
      <footer className="app__footer">
        Charts of Rehan. Bars come only from sources this project can name;
        an empty series is shown as empty, never as zero.
      </footer>
    </div>
  );
}
