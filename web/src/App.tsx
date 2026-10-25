/**
 * The application shell, in TradingView's shape for the PSX tape.
 *
 * A thin rail on the left for the working toggles, the chart taking every
 * pixel between it and the watchlist, and the watchlist pane on the right
 * holding exactly the symbols the reader put on it. The heavy status text
 * lives behind a single "data detail" fold, and the chart's own state bar
 * stays where a reader reads it: under the candles.
 *
 * What lives here is only what a human chooses (symbol, resolution, session,
 * theme, watchlist) and what the service says about itself. The series
 * belongs to the feed hook and the pixels belong to the canvas.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, ChartClient } from "./api/client";
import {
  type PrintEvent,
  type Resolution,
  type SessionRow,
  type SymbolRow,
  parseHealth,
} from "./api/types";
import { ChartCanvas } from "./components/ChartCanvas";
import { Screener } from "./components/Screener";
import {
  ChartSettingsDialog,
  IndicatorSettingsDialog,
} from "./components/SettingsDialog";
import { DrawToolRail } from "./components/DrawToolRail";
import { IndicatorsPanel } from "./components/IndicatorsPanel";
import { NotesPanel } from "./components/NotesPanel";
import { StatusBar } from "./components/StatusBar";
import { SymbolSearch } from "./components/SymbolSearch";
import { Toolbar } from "./components/Toolbar";
import { Watchlist } from "./components/Watchlist";
import { useChartFeed } from "./hooks/useChartFeed";
import { useAppearance } from "./hooks/useAppearance";
import { useIndicators } from "./hooks/useIndicators";
import { usePrints } from "./hooks/usePrints";
import { timeframeShort } from "./chart/timeframes";
import { definitionFor } from "./indicators/registry";
import {
  clearDrawings,
  loadDrawings,
  saveDrawings,
  type Drawing,
  type DrawTool,
} from "./chart/drawings";

const FALLBACK_RESOLUTIONS: readonly Resolution[] = ["1m"];

/** A session in play for longer than this gets a visible warning (minutes). */
const STALE_AFTER_MINUTES = 12;

/**
 * How many sessions the default chart spans.
 *
 * One: the chart opens on this session, the way TradingView opens on the
 * live one. Panning back is the reader's own move, and the session selector
 * offers any stored day as a snapshot; a chart that silently stitched five
 * days together read as a clock running backwards between them.
 */
const SPAN_SESSIONS = 1;

const WATCHLIST_KEY = "charts-watchlist";

/**
 * The chart this browser last opened.
 *
 * Opening the app used to land on whatever the catalogue listed first, which
 * is an index: every visit began on KSE100 no matter what the reader was
 * charting last night. The last symbol you charted is the one you meant to
 * see again, so it is kept beside the watchlist and reopened on the next
 * visit. A first visit has no last symbol and falls back to the session's
 * own most traded name.
 */
const LAST_SYMBOL_KEY = "charts-symbol";

/** One shared empty list, so a poll without a ledger never re-renders. */
const EMPTY_PRINTS: readonly PrintEvent[] = [];

/** The list a reader starts with: the two breadth indexes the tape computes. */
const DEFAULT_WATCHLIST: readonly string[] = ["KSE100", "KMIALLSHR"];

function readWatchlist(): string[] {
  try {
    const raw = window.localStorage.getItem(WATCHLIST_KEY);
    if (raw !== null) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.filter((item): item is string =>
          typeof item === "string" && item.length > 0).slice(0, 64);
      }
    }
  } catch {
    // A corrupt note is still a note, not a crash: the default returns.
  }
  return [...DEFAULT_WATCHLIST];
}

function readLastSymbol(): string {
  try {
    const stored = window.localStorage.getItem(LAST_SYMBOL_KEY);
    return stored === null ? "" : stored.trim().toUpperCase();
  } catch {
    return ""; // a disabled storage is a first visit, not a crash
  }
}

/**
 * The name a first visit opens.
 *
 * The most traded scrip of the session, never a computed index: a reader who
 * has never chosen anything is better served by the tape's busiest symbol
 * than by a breadth gauge. An index answers only when nothing in the
 * catalogue traded at all.
 */
export function openingSymbol(
  items: readonly SymbolRow[],
): SymbolRow | undefined {
  const traded = items.filter((row) => (row.bars ?? 0) > 0);
  const named = traded.filter((row) => row.index !== true);
  const pool = named.length > 0 ? named : traded;
  if (pool.length === 0) {
    return items[0];
  }
  let best = pool[0];
  for (const row of pool) {
    if ((row.volume ?? 0) > (best?.volume ?? 0)) {
      best = row;
    }
  }
  return best;
}

function hash(): { symbol: string; day: string } {
  const raw = window.location.hash.replace(/^#/, "");
  const [symbol = "", day = ""] = raw.split("/");
  return { symbol: symbol.trim().toUpperCase(), day: day.trim() };
}

export function App() {
  const client = useMemo(() => new ChartClient(), []);
  const initial = useMemo(hash, []);
  const [symbol, setSymbol] = useState(
    () => initial.symbol.length > 0 ? initial.symbol : readLastSymbol(),
  );
  const [day, setDay] = useState(initial.day);
  const [resolution, setResolution] = useState<Resolution>("1m");
  const [resolutions, setResolutions] =
    useState<readonly Resolution[]>(FALLBACK_RESOLUTIONS);
  const [rows, setRows] = useState<readonly SymbolRow[]>([]);
  const [sessions, setSessions] = useState<readonly SessionRow[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);
  const [catalogueLoading, setCatalogueLoading] = useState(true);
  const [watchlistOpen, setWatchlistOpen] = useState(true);
  const [indicatorsOpen, setIndicatorsOpen] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [screenerOpen, setScreenerOpen] = useState(false);
  const [watch, setWatch] = useState<readonly string[]>(readWatchlist);
  const indicators = useIndicators();
  const [appearance, setAppearance, resetAppearance] = useAppearance();
  const [chartSettingsOpen, setChartSettingsOpen] = useState(false);
  const [indicatorTarget, setIndicatorTarget] = useState<string | null>(null);

  // The drawings the reader keeps on this chart, one tool at a time.
  const [tool, setTool] = useState<DrawTool>("cursor");
  const [drawingsHidden, setDrawingsHidden] = useState(false);
  const viewKey = `${symbol}|${day}|${resolution}`;
  const [drawings, setDrawings] = useState<readonly Drawing[]>(
    () => loadDrawings(`${initial.symbol}|${initial.day}|1m`),
  );
  useEffect(() => {
    setDrawings(loadDrawings(viewKey));
  }, [viewKey]);
  const onDrawingComplete = useCallback((drawing: Drawing) => {
    setDrawings((current) => {
      const next = [...current, drawing];
      saveDrawings(viewKey, next);
      return next;
    });
  }, [viewKey]);
  const onClearDrawings = useCallback(() => {
    clearDrawings(viewKey, window.localStorage);
    setDrawings([]);
  }, [viewKey]);

  useEffect(() => {
    window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watch));
  }, [watch]);

  // The chart you were reading is the chart you get back.
  useEffect(() => {
    if (symbol.length > 0) {
      try {
        window.localStorage.setItem(LAST_SYMBOL_KEY, symbol);
      } catch {
        // A full storage must never stop the chart from opening.
      }
    }
  }, [symbol]);

  // The service's own facts, read once per mount and again after a refresh.
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
            health.resolutions.length > 0 ? health.resolutions : FALLBACK_RESOLUTIONS,
          );
          setResolution((current) =>
            health.resolutions.includes(current)
              ? current
              : (health.resolutions[0] ?? "1m"),
          );
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
      .sessions()
      .then((report) => {
        if (!cancelled) {
          setSessions(report.sessions);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client]);

  // The catalogue with the chosen session's own facts, for the watchlist.
  useEffect(() => {
    let cancelled = false;
    setCatalogueLoading(true);
    client
      .symbolRows(day)
      .then((items) => {
        if (!cancelled) {
          setRows(items);
          setCatalogueLoading(false);
          // Opening on a chart the reader put in the list is the point of a
          // watchlist; only when there is none does the session's own most
          // traded symbol answer.
          const first = openingSymbol(items);
          setSymbol((current) =>
            current.length > 0 ? current : (first?.symbol ?? ""));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRows([]);
          setCatalogueLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, day]);

  const feed = useChartFeed(client, symbol, resolution, {
    day,
    days: day.length === 0 ? SPAN_SESSIONS : undefined,
  });

  // The order ledger, polled on the tape's own minute grain. It follows the
  // day the reader is on: the live tape while the selector says “recent,"
  // that day's stored capture when a specific session is chosen.
  const prints = usePrints(client, symbol, feed.meta.session?.day ?? day,
    symbol.length > 0);

  const chooseSymbol = useCallback((next: string) => {
    setSymbol(next);
    setSearchOpen(false);
    window.location.hash = day.length > 0 ? `${next}/${day}` : next;
  }, [day]);

  const chooseDay = useCallback((next: string) => {
    setDay(next);
    window.location.hash = next.length > 0 ? `${symbol}/${next}` : symbol;
  }, [symbol]);

  const bars = feed.meta.payload?.bar_count ?? feed.series.length;
  const session = feed.meta.session;
  const missingMinutes = feed.meta.gaps.reduce(
    (total, gap) => total + Math.round(gap.minutes), 0);

  const emptyNote = useMemo(() => {
    if (symbol.length === 0) {
      return "Choose a symbol to draw.";
    }
    if (feed.meta.payload === null) {
      return "Waiting for the service to answer…";
    }
    if (session !== null && session.note.length > 0) {
      return session.note;
    }
    return `No bar exists for ${symbol} in this session yet. That is an absence ` +
      `of data, not a price of zero.`;
  }, [feed.meta.payload, session, symbol]);

  const sessionLabel = session === null || session.day.length === 0
    ? "No session reported."
    : `${session.day}${session.archived ? ", stored session" : ""}.`;

  const watchComplete = useMemo(() => {
    const shown = new Set(watch);
    return symbol.length > 0 && !shown.has(symbol)
      ? [...watch, symbol]
      : watch;
  }, [watch, symbol]);

  return (
    <div className={["app", watchlistOpen ? "app--with-watchlist" : ""]
      .filter(Boolean).join(" ")}>
      <Toolbar
        symbol={symbol}
        resolution={resolution}
        onResolution={setResolution}
        resolutions={resolutions}
        day={day}
        onDay={chooseDay}
        sessions={sessions}
        onRefresh={feed.refresh}
        busy={feed.status === "loading"}
        watchlistOpen={watchlistOpen}
        onToggleWatchlist={() => setWatchlistOpen((open) => !open)}
        indicatorsOpen={indicatorsOpen}
        onToggleIndicators={() => setIndicatorsOpen((open) => !open)}
        onSearch={() => setSearchOpen(true)}
        onOpenSettings={() => setChartSettingsOpen(true)}
        screenerOpen={screenerOpen}
        onToggleScreener={() => setScreenerOpen((open) => !open)}
      />

      {/* The studies sit in a strip above the chart, not in a side column:
          the candles keep every pixel of width. */}
      {indicatorsOpen ? (
        <IndicatorsPanel controller={indicators} onOpen={setIndicatorTarget} />
      ) : null}

      <div className="app__body">
        <DrawToolRail
          tool={tool}
          onTool={setTool}
          hidden={drawingsHidden}
          onHideToggle={() => setDrawingsHidden((hidden) => !hidden)}
          count={drawings.length}
          onClear={onClearDrawings}
        />

        <main className="app__main">
          <ChartCanvas
            series={feed.series}
            gaps={feed.meta.gaps}
            resolution={resolution}
            viewKey={`${symbol}|${day}|${resolution}`}
            version={feed.version}
            volumeAvailable={session?.volume_available ?? false}
            sessionLabel={sessionLabel}
            emptyNote={emptyNote}
            indicators={indicators.specs}
            prints={prints.report?.events ?? EMPTY_PRINTS}
            printTotals={prints.report?.totals ?? null}
            heading={symbol.length > 0
              ? `${symbol} · ${timeframeShort(resolution)} · PSX`
              : ""}
            live={feed.status === "live"}
            tool={tool}
            drawings={drawings as readonly Drawing[]}
            drawingsHidden={drawingsHidden}
            onDrawingComplete={onDrawingComplete}
            appearance={appearance}
          />
          <StatusBar
            status={feed.status}
            resolution={resolution}
            market={feed.meta.market}
            symbol={feed.meta.symbol || symbol}
            day={session?.day ?? day}
            sessionNote={session?.note ?? ""}
            archived={session?.archived ?? false}
            captureName={session?.source ?? ""}
            sha256={session?.capture?.sha256 ?? ""}
            bars={bars}
            gaps={feed.meta.gaps.length}
            missingMinutes={missingMinutes}
            sourceLabel={feed.meta.source?.label ?? ""}
            delaySeconds={feed.meta.source?.delay_seconds ?? 0}
            lastBarAt={feed.meta.payload?.bars.at(-1)?.t ?? ""}
            asOf={feed.meta.payload?.as_of ?? ""}
            volumeAvailable={session?.volume_available ?? false}
            staleAfterMinutes={STALE_AFTER_MINUTES}
            ordersTotal={prints.report?.totals?.orders ?? null}
            error={feed.error ?? (bootError === null ? null
              : { category: "INTERNAL", detail: bootError })}
            details={detailsOpen}
          />
          <button
            type="button"
            className="app__details-toggle"
            aria-expanded={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            {detailsOpen ? "hide data detail" : "show data detail"}
          </button>
          {detailsOpen ? <NotesPanel meta={feed.meta} /> : null}
          {screenerOpen ? (
            <Screener
              rows={rows}
              loading={catalogueLoading}
              day={day}
              onSymbol={(next) => {
                chooseSymbol(next);
                setScreenerOpen(false);
              }}
              onClose={() => setScreenerOpen(false)}
            />
          ) : null}
        </main>

        {watchlistOpen ? (
          <Watchlist
            rows={rows}
            watch={watchComplete}
            symbol={symbol}
            day={day}
            loading={catalogueLoading}
            onSymbol={(next) => {
              chooseSymbol(next);
            }}
            onWatchChange={setWatch}
            searchOpen={searchOpen}
            onSearchOpen={() => setSearchOpen(true)}
            onSearchClose={() => setSearchOpen(false)}
          />
        ) : (
          <SymbolSearch
            open={searchOpen}
            rows={rows}
            loading={catalogueLoading}
            action="add"
            onPick={chooseSymbol}
            onClose={() => setSearchOpen(false)}
          />
        )}
      </div>

      {chartSettingsOpen ? (
        <ChartSettingsDialog
          appearance={appearance}
          onAppearance={setAppearance}
          onReset={resetAppearance}
          onClose={() => setChartSettingsOpen(false)}
        />
      ) : null}
      {indicatorTarget !== null ? (() => {
        const spec = indicators.specs.find((item) => item.id === indicatorTarget);
        if (spec === undefined) {
          return null;
        }
        return (
          <IndicatorSettingsDialog
            spec={spec}
            definition={definitionFor(spec.type)}
            controller={indicators}
            onClose={() => setIndicatorTarget(null)}
          />
        );
      })() : null}
    </div>
  );
}
