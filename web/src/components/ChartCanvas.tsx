/**
 * The chart surface: TradingView's own engine, bound to the PSX tape.
 *
 * The renderer is `lightweight-charts`, TradingView's open-source engine
 * (Apache-2.0), so pan, zoom, the price scale, the crosshair and the candles
 * are drawn by their code. The plate is true black (#000) with one step of
 * separation for the grid (#141414) and the borders (#1f1f1f), the candles
 * are TV's own teal (#089981) and red (#f23645), the crosshair is #758696
 * and the type is Trebuchet MS. Their attribution badge is switched off: the
 * chart is the owner's, and nothing here links off the page.
 *
 * The drawing rule survives from the previous renderer: React re-renders
 * for metadata only, the engine owns the pixels, and a pointer move goes
 * through one subscription that writes a DOM node, never a rendered tree.
 * The tape owns time exactly as before: bars live in the Karachi clock and
 * reach the engine as UTC seconds, with the tick marks labelled explicitly
 * in Asia/Karachi, so a viewer in any zone reads the exchange's clock.
 *
 * The honesty features keep their place: an empty window says so on the
 * chart, and the order tape (the venue's own counters) is the floating
 * surface that draws when the tape has something to show.
 */

import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  LineStyle,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
  TickMarkType,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  ColorType,
  createChart,
  createTextWatermark,
} from "lightweight-charts";
import {
  useEffect,
  useMemo,
  useRef,
} from "react";

import type { Gap, PrintEvent, PrintTotals, Resolution } from "../api/types";
import {
  measureBetween,
  newDrawingId,
  type AnchoredPoint,
  type Drawing,
  type DrawTool,
  type MeasureResult,
} from "../chart/drawings";
import {
  anchorAt,
  frameFor,
  paintOverlay,
} from "../chart/overlay";
import { formatClock, formatPrice, formatVolume } from "../chart/format";
import { type ColumnSeries } from "../chart/series";
import type { ChartAppearance } from "../hooks/useAppearance";
import type {
  IndicatorOutput,
  IndicatorSpec,
  SeriesData,
} from "../indicators/types";
import { computeIndicators, seriesData } from "../indicators/compute";

const MIN_WIDTH = 320;
const MIN_HEIGHT = 220;
const TAPE_ROWS = 9;
const RIGHT_OFFSET_BARS = 5;

/** The chart's colour tokens: one theme, black, with TV's own candle hues. */
export interface TvTheme {
  readonly background: string;
  readonly grid: string;
  readonly text: string;
  readonly border: string;
  readonly up: string;
  readonly down: string;
  readonly volumeUp: string;
  readonly volumeDown: string;
  readonly crosshair: string;
  readonly labelBack: string;
  readonly watermark: string;
}

/**
 * Black, and only black.
 *
 * The chart used to sit on TV's slate (#131722), which reads grey once it
 * fills a screen. The plate is now true black so the candles, the grid and
 * the axes are the only things with weight on it; the grid and the borders
 * are one step off black so they separate without becoming lines of their
 * own. The candle hues stay TV's own teal and red.
 */
export const TV_DARK_THEME: TvTheme = {
  background: "#000000",
  grid: "#141414",
  text: "#d1d4dc",
  border: "#1f1f1f",
  up: "#089981",
  down: "#f23645",
  volumeUp: "rgba(8, 153, 129, 0.45)",
  volumeDown: "rgba(242, 54, 69, 0.45)",
  crosshair: "#758696",
  labelBack: "#2a2a2a",
  watermark: "rgba(120, 123, 134, 0.16)",
};

export interface ChartCanvasProps {
  readonly series: ColumnSeries;
  readonly gaps: readonly Gap[];
  readonly resolution: Resolution;
  /** Symbol, session and timeframe: a new value means a new chart. */
  readonly viewKey: string;
  readonly version: number;
  readonly volumeAvailable: boolean;
  /** A sentence for the accessible description: which session is on screen. */
  readonly sessionLabel: string;
  /** What to say when there is nothing to draw, and why. */
  readonly emptyNote: string;
  /** Configured indicators; unlimited overlays, up to eight panes. */
  readonly indicators: readonly IndicatorSpec[];
  /** Order prints the tape carried, drawn as markers on their candles. */
  readonly prints?: readonly PrintEvent[];
  /** The venue's own session counters, for the on-chart order tape. */
  readonly printTotals?: PrintTotals | null;
  /** The chart headline, TV-style: `PRL · 1h · PSX` watermark. */
  readonly heading?: string;
  /** True while a live stream is open; the chart itself does not need it. */
  readonly live?: boolean;
  /** The active drawing tool, or "cursor" when the chart is being read. */
  readonly tool?: DrawTool;
  /** Committed drawings on this chart, oldest first. */
  readonly drawings?: readonly Drawing[];
  /** Every drawing hidden, the eye toggle. */
  readonly drawingsHidden?: boolean;
  /** A drawing the reader just committed: the note belongs to the app. */
  readonly onDrawingComplete?: (drawing: Drawing) => void;
  /** The settings dialog's appearance: colours and what shows behind price. */
  readonly appearance?: ChartAppearance;
}

interface PaneRef {
  readonly lines: readonly ISeriesApi<"Line", Time>[];
  readonly histogram?: ISeriesApi<"Histogram", Time>;
}

interface EngineState {
  readonly chart: IChartApi;
  readonly candles: ISeriesApi<"Candlestick", Time>;
  readonly volume: ISeriesApi<"Histogram", Time> | null;
  readonly panes: Map<string, PaneRef>;
  /** epoch-second → bar index, for the legend's previous close. */
  readonly index: Map<number, number>;
  readonly volumeShown: boolean;
  data: SeriesData | null;
}

/** A hex colour at an alpha, for the muted volume under the candles. */
function withAlpha(hex: string, alpha: number): string {
  const raw = /^#([0-9a-fA-F]{6})$/.exec(hex);
  const digits = raw?.[1];
  if (digits === undefined) {
    return hex;
  }
  const value = Number.parseInt(digits, 16);
  const r = (value >> 16) & 0xff;
  const g = (value >> 8) & 0xff;
  const b = value & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** decimals the tape's own closes use, so the axis is exact. */
function decimalsFrom(values: readonly number[]): number {
  let best = 0;
  for (const value of values) {
    if (!Number.isFinite(value) || value <= 0) {
      continue;
    }
    const text = value.toString();
    const dot = text.indexOf(".");
    const digits = dot === -1 ? 0 : text.length - dot - 1;
    if (digits > best) {
      best = Math.min(digits, 4);
    }
  }
  return best;
}

const karachiClock = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Karachi",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const karachiStamp = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Karachi",
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const karachiDay = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Karachi",
  day: "2-digit",
  month: "short",
});

export function ChartCanvas(props: ChartCanvasProps) {
  const {
    series,
    resolution,
    viewKey,
    version,
    volumeAvailable,
    sessionLabel,
    emptyNote,
    indicators,
    prints,
    printTotals,
    heading,
    live,
    tool,
    drawings,
    drawingsHidden,
    onDrawingComplete,
    appearance,
  } = props;
  void live; // the status bar owns liveness; the chart owns candles
  void props.gaps; // the status bar owns the gap ledger; see it there


  const wrapper = useRef<HTMLDivElement | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  const legend = useRef<HTMLDivElement | null>(null);
  const engine = useRef<EngineState | null>(null);
  const fitKey = useRef("");
  const fitCount = useRef(0);
  /** True once the reader pans, zooms or drags: no fit after that. */
  const zoomed = useRef(false);

  // The drawing overlay: its canvas, the capture in progress and one
  // batched repaint, so a pointer move costs one frame, not a render.
  const overlay = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<{
    kind: "trend" | "flatTop" | "flatBottom" | "measure";
    a: AnchoredPoint;
    b: AnchoredPoint | null;
  } | null>(null);
  const paintQueued = useRef(false);

  const showSeconds = resolution === "1s" || resolution === "10s";

  /**
   * TV's tick marks and axis: the Karachi clock, whatever the viewer's PC.
   *
   * A tick that lands on a day's first bar is labelled with the day itself -
   * "23 Oct" - exactly as TV does. Two sessions on one chart otherwise read
   * as a clock that jumps backwards, which is precisely how a merged chart
   * was being misread.
   */
  const tickLabel = useMemo(() => {
    const secondsFormat = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Karachi",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    return (time: Time, markType: TickMarkType): string => {
      const moment = new Date(Number(time) * 1000);
      if (Number.isNaN(moment.getTime())) {
        return "";
      }
      if (markType === TickMarkType.DayOfMonth
        || markType === TickMarkType.Month
        || markType === TickMarkType.Year) {
        return karachiDay.format(moment);
      }
      return showSeconds ? secondsFormat.format(moment)
        : karachiClock.format(moment);
    };
  }, [showSeconds]);

  /** The indicator plan: the chart engine rebuilds when the plan changes. */
  const indicatorsKey = useMemo(
    () => indicators
      .map((spec) =>
        `${spec.id}:${spec.type}:${spec.placement ?? ""}:${spec.color}:` +
        `${JSON.stringify(spec.params)}`)
      .join("|"),
    [indicators],
  );

  /** A one-token identity of the dialog's appearance, for the engine deps. */
  const appearanceKey = useMemo(
    () => appearance === undefined ? "" : JSON.stringify(appearance),
    [appearance],
  );

  useEffect(() => {
    const surfaceEl = surface.current;
    if (surfaceEl === null) {
      return;
    }
    const tokens = { ...TV_DARK_THEME };
    if (appearance !== undefined) {
      // The volume bars wear the candles' own colours at TV's muted alpha.
      tokens.up = appearance.up;
      tokens.down = appearance.down;
      tokens.volumeUp = withAlpha(appearance.up, 0.45);
      tokens.volumeDown = withAlpha(appearance.down, 0.45);
    }

    // The decimals come from the tape's own closes, before any axis print.
    const columns = series.columns();
    const decimals = decimalsFrom(Array.from(columns.close));

    const chart = createChart(surfaceEl, {
      width: surfaceEl.clientWidth || MIN_WIDTH,
      height: surfaceEl.clientHeight || MIN_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: tokens.background },
        textColor: tokens.text,
        // No TV badge, and no link off this page: the chart is the owner's.
        attributionLogo: false,
        fontFamily: "'Trebuchet MS', 'Segoe UI', Verdana, sans-serif",
        panes: { separatorColor: tokens.border },
      },
      grid: appearance?.gridOn === false
        ? { vertLines: { visible: false }, horzLines: { visible: false } }
        : {
            vertLines: { color: tokens.grid },
            horzLines: { color: tokens.grid },
          },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: tokens.crosshair,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: tokens.labelBack,
        },
        horzLine: {
          color: tokens.crosshair,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: tokens.labelBack,
        },
      },
      rightPriceScale: {
        borderColor: tokens.border,
        // Room for the volume bars at the foot of the price pane, so a candle
        // never hides behind them.
        scaleMargins: volumeAvailable
          ? { top: 0.08, bottom: 0.24 }
          : { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: tokens.border,
        rightOffset: RIGHT_OFFSET_BARS,
        barSpacing: 8,
        timeVisible: true,
        secondsVisible: showSeconds,
        tickMarkFormatter:
          (time: Time, markType: TickMarkType) => tickLabel(time, markType),
      },
      localization: {
        priceFormatter: (price: number) => formatPrice(price, decimals),
      },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: tokens.up,
      downColor: tokens.down,
      wickUpColor: tokens.up,
      wickDownColor: tokens.down,
      borderVisible: false,
      priceLineVisible: true,
      priceLineColor: tokens.crosshair,
      priceLineStyle: LineStyle.Dashed,
      lastValueVisible: true,
    });

    let volume: ISeriesApi<"Histogram", Time> | null = null;
    if (volumeAvailable) {
      // Volume rides an overlay scale of the price pane - no axis of its own,
      // no pane of its own - held to the bottom fifth as TV draws it, so the
      // bars sit under the candles and never stretch the price axis.
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceScaleId: "",
        priceLineVisible: false,
        lastValueVisible: false,
        base: 0,
        priceFormat: { type: "volume", precision: 0, minMove: 1 },
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
      });
      volume = volumeSeries;
    }

    // The TV watermark: the symbol, then the timeframe, behind the candles.
    if (heading !== undefined && heading.length > 0
        && appearance?.watermarkOn !== false) {
      const parts = heading.split("·");
      const symbolLine = (parts[0] ?? "").trim();
      const restLine = parts.slice(1).join("·").trim();
      const pricePane = chart.panes()[0];
      if (pricePane !== undefined) {
        createTextWatermark(pricePane, {
          horzAlign: "center",
          vertAlign: "center",
          lines: [
            { text: symbolLine, color: tokens.watermark, fontSize: 44 },
            ...(restLine.length > 0
              ? [{ text: restLine, color: tokens.watermark, fontSize: 26 }]
              : []),
          ],
        });
      }
    }

    // The pointer readout: one browser callback, one DOM write, no renders.
    const onCrosshair = (param: MouseEventParams) => {
      const state = engine.current;
      const legendEl = legend.current;
      if (state === null || legendEl === null) {
        return;
      }
      if (param.time === undefined || param.point === undefined) {
        // Left the chart: the legend falls back to the newest bar.
        const last = state.data === null ? undefined
          : state.data.length - 1;
        writeLegend(state, last, legendEl, volumeAvailable);
        return;
      }
      writeLegend(state, state.index.get(Number(param.time)),
        legendEl, volumeAvailable);
    };
    chart.subscribeCrosshairMove(onCrosshair);

    const resize = () => {
      chart.applyOptions({
        width: Math.max(MIN_WIDTH, surfaceEl.clientWidth),
        height: Math.max(MIN_HEIGHT, surfaceEl.clientHeight),
      });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(surfaceEl);
    resize();

    // Any real gesture is the reader taking the window: from then on the
    // chart keeps their zoom, whatever data lands.
    const tookTheWindow = () => {
      zoomed.current = true;
    };
    surfaceEl.addEventListener("wheel", tookTheWindow, { passive: true });
    surfaceEl.addEventListener("pointerdown", tookTheWindow);

    // Pan or zoom moves the drawings too: repaint once per viewport change.
    const rangeSub = () => scheduleOverlayPaint();
    chart.timeScale().subscribeVisibleTimeRangeChange(rangeSub);

    engine.current = {
      chart,
      candles,
      volume,
      panes: new Map(),
      index: new Map(),
      volumeShown: volumeAvailable,
      data: null,
    };

    // The price pane is the chart; a study pane beneath it is a detail, so
    // the candles keep the height and the studies share what is left.
    chart.panes()[0]?.setStretchFactor(4);

    // A rebuilt engine draws the bars it already has: a new study must never
    // leave an empty plate waiting for the market to move.
    fitKey.current = "";
    fitCount.current = 0;
    zoomed.current = false;
    paintData();

    return () => {
      observer.disconnect();
      surfaceEl.removeEventListener("wheel", tookTheWindow);
      surfaceEl.removeEventListener("pointerdown", tookTheWindow);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(rangeSub);
      chart.unsubscribeCrosshairMove(onCrosshair);
      chart.remove();
      engine.current = null;
    };
    // The full build is keyed to the chart's identity only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, indicatorsKey, volumeAvailable, appearanceKey]);

  /**
   * One pass of the tape into the engine: candles, the volume plate, the
   * study series, the legend, and the single fit a new view gets. It runs
   * when bars arrive and again right after an engine is rebuilt, so a rebuild
   * is never a blank chart waiting for the next tick.
   *
   * Times go in strictly increasing order because the engine asserts it: a
   * repeated instant (two sources, one minute) is drawn once, at the newest
   * reading, rather than throwing the whole series away.
   */
  function paintData(): void {
    const state = engine.current;
    if (state === null) {
      return;
    }
    const data = seriesData(series);
    const length = data.time.length;
    if (length === 0) {
      return;
    }
    const tokens = TV_DARK_THEME;
    state.data = data;
    state.index.clear();

    const candlesData: CandlestickData[] = [];
    const volumeData: HistogramData[] = [];
    let previous = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < length; i += 1) {
      const t = data.time[i];
      const open = data.open[i];
      const high = data.high[i];
      const low = data.low[i];
      const close = data.close[i];
      if (t === undefined || open === undefined || high === undefined
        || low === undefined || close === undefined) {
        continue;
      }
      if (!Number.isFinite(open) || !Number.isFinite(high)
        || !Number.isFinite(low) || !Number.isFinite(close)) {
        continue; // a bar the tape never priced is not a price of zero
      }
      const seconds = Math.floor(t / 1000);
      if (seconds <= previous) {
        continue;
      }
      previous = seconds;
      state.index.set(seconds, i);
      candlesData.push({
        time: seconds as UTCTimestamp, open, high, low, close,
      });
      const value = data.volume[i];
      if (value !== undefined && Number.isFinite(value)) {
        volumeData.push({
          time: seconds as UTCTimestamp,
          value,
          color: close >= open ? tokens.volumeUp : tokens.volumeDown,
        });
      }
    }
    if (candlesData.length === 0) {
      return;
    }
    state.candles.setData(candlesData);
    if (state.volumeShown && state.volume !== null) {
      state.volume.setData(volumeData);
    }

    buildIndicators(state, indicators, data, tokens);

    const legendEl = legend.current;
    if (legendEl !== null) {
      writeLegend(state, length - 1, legendEl, state.volumeShown);
    }

    // Fit in logical bars rather than pixels, so the window is the same
    // whatever width the pane happened to have when the data landed. A view
    // change refits; so does a wider dataset arriving while the reader has
    // not touched the chart (a merged span lands after the live snapshot of
    // one session, and the chart must show the span, not the snapshot). Once
    // the reader pans or zooms, nothing here moves their window again.
    const widened = candlesData.length > fitCount.current;
    if (fitKey.current !== viewKey || (!zoomed.current && widened)) {
      fitKey.current = viewKey;
      fitCount.current = candlesData.length;
      state.chart.timeScale().setVisibleLogicalRange({
        from: 0,
        to: candlesData.length - 1 + RIGHT_OFFSET_BARS,
      });
    }
  }

  useEffect(() => {
    paintData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const hasBars = series.length > 0;
  const activeTool = tool ?? "cursor";
  const drawingActive = activeTool !== "cursor";

  useEffect(() => {
    if (!drawingActive) {
      const pressed = (event: KeyboardEvent) => {
        if (event.key === "Escape") {
          dragRef.current = null;
          scheduleOverlayPaint();
        }
      };
      window.addEventListener("keydown", pressed, { capture: true });
      return () =>
        window.removeEventListener("keydown", pressed, { capture: true });
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingActive]);

  useEffect(() => {
    scheduleOverlayPaint();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, drawings, drawingsHidden, version, viewKey]);

  const scheduleOverlayPaint = () => {
    if (paintQueued.current) {
      return;
    }
    paintQueued.current = true;
    requestAnimationFrame(() => {
      paintQueued.current = false;
      paintOverlayNow();
    });
  };

  const paintOverlayNow = () => {
    const canvas = overlay.current;
    const wrapperEl = wrapper.current;
    const state = engine.current;
    if (canvas === null || wrapperEl === null || state === null) {
      return;
    }
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const cssWidth = wrapperEl.clientWidth;
    const cssHeight = wrapperEl.clientHeight;
    if (canvas.width !== Math.round(cssWidth * dpr)
      || canvas.height !== Math.round(cssHeight * dpr)) {
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(cssHeight * dpr);
    }
    const context = canvas.getContext("2d");
    if (context === null) {
      return;
    }
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    const frame = frameFor(state.chart, cssWidth, cssHeight);
    const drag = dragRef.current;
    const midDrag: MeasureResult | null = drag !== null
      && drag.kind === "measure" && drag.b !== null
      ? measureBetween(drag.a, drag.b)
      : null;
    paintOverlay(context, state.chart, state.candles, frame, {
      drawings: drawings ?? [],
      hidden: drawingsHidden ?? false,
      toolColor: "#2962ff",
      midDrag,
    });
    if (drag !== null) {
      paintLive(context, state.chart, state.candles, frame, drag);
    }
  };

  const paintLive = (
    context: CanvasRenderingContext2D,
    chart: ReturnType<typeof createChart>,
    candles: ISeriesApi<"Candlestick", Time>,
    frame: ReturnType<typeof frameFor>,
    drag: NonNullable<typeof dragRef.current>,
  ) => {
    if (drag.b === null) {
      return;
    }
    if (drag.kind === "measure") {
      return; // painted by paintOverlay's measure block
    }
    const points: [AnchoredPoint, AnchoredPoint | null] =
      drag.kind === "flatTop" || drag.kind === "flatBottom"
        // A flat never slants: hold the first anchor's level.
        ? [{ t: drag.a.t, price: drag.a.price },
           { t: drag.b.t, price: drag.a.price }]
        : [drag.a, drag.b];
    paintOne(context, chart, candles, frame, {
      id: "live",
      kind: drag.kind,
      points,
    });
  };

  const onOverlayDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const state = engine.current;
    if (state === null || !drawingActive) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const anchor = anchorAt(state.chart, state.candles, x, y);
    if (anchor === null) {
      return;
    }
    if (activeTool === "hline" || activeTool === "hray") {
      const drawing: Drawing = {
        id: newDrawingId(),
        kind: activeTool,
        points: [anchor, null],
      };
      onDrawingComplete?.(drawing);
      return;
    }
    dragRef.current = {
      kind: activeTool === "trend" ? "trend"
        : activeTool === "flatTop" ? "flatTop"
        : activeTool === "flatBottom" ? "flatBottom"
        : "measure",
      a: anchor,
      b: null,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // A synthetic pointer (assistive or test) cannot be captured; keep it.
    }
    scheduleOverlayPaint();
  };

  const onOverlayMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    const state = engine.current;
    if (drag === null || state === null) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const anchor = anchorAt(
      state.chart,
      state.candles,
      event.clientX - rect.left,
      event.clientY - rect.top,
    );
    if (anchor !== null) {
      drag.b = anchor;
      scheduleOverlayPaint();
    }
  };

  const onOverlayUp = () => {
    const drag = dragRef.current;
    const state = engine.current;
    if (drag === null || state === null) {
      return;
    }
    dragRef.current = null;
    if (drag.kind === "measure") {
      scheduleOverlayPaint();
      return; // a measure is read, never kept
    }
    const points: [AnchoredPoint, AnchoredPoint | null] =
      drag.kind === "flatTop" || drag.kind === "flatBottom"
        ? [{ t: drag.a.t, price: drag.a.price },
           drag.b === null
             ? null
             : { t: drag.b.t, price: drag.a.price }]
        : [drag.a, drag.b];
    onDrawingComplete?.({
      id: newDrawingId(),
      kind: drag.kind,
      points,
    });
    scheduleOverlayPaint();
  };

  return (
    <div className="chart tv-chart" ref={wrapper}>
      <div
        ref={surface}
        className="chart__canvas chart__tv"
        tabIndex={0}
        aria-label={`candlestick chart. ${sessionLabel} ${series.length} bars. ` +
          "Drag to pan, wheel to zoom."}
        data-bars={series.length}
      />
      {!hasBars ? (
        <p className="chart__empty" role="status">
          {emptyNote}
        </p>
      ) : null}
      {/* The TV legend: OHLC + change, live under the pointer. */}
      <div className="tv-legend" ref={legend} aria-live="off" />
      {/* The drawing overlay: interactive only while a tool is picked, so
          reading (pan, zoom, crosshair) is never blocked by it. */}
      <canvas
        ref={overlay}
        className="tv-overlay"
        style={drawingActive
          ? { pointerEvents: "auto", cursor: "crosshair" }
          : { pointerEvents: "none" } as React.CSSProperties}
        onPointerDown={onOverlayDown}
        onPointerMove={onOverlayMove}
        onPointerUp={onOverlayUp}
        onPointerCancel={onOverlayUp}
        aria-hidden={drawingActive ? "false" : "true"}
        aria-label={drawingActive
          ? "drawing surface: click or drag to place the selected tool"
          : "drawings"}
      />
      {printTape(prints, printTotals)}
    </div>
  );
}

/**
 * The TV legend, written straight into one DOM node. Every field wears the
 * bar's own colour: teal above the prior close, red below, grey when flat.
 * When the series carries a volume counter the readout ends with it.
 */
function writeLegend(
  state: EngineState,
  at: number | undefined,
  legendEl: HTMLElement,
  withVolume: boolean,
): void {
  if (at === undefined || state.data === null
    || at < 0 || at >= state.data.length) {
    return;
  }
  const i = at;
  const close = state.data.close[i];
  if (close === undefined) {
    return;
  }
  const priorRaw = i > 0 ? state.data.close[i - 1] : close;
  const prior = priorRaw ?? close;
  const change = close - prior;
  const changePct = prior !== 0 ? (change / prior) * 100 : 0;
  const tone = change > 0 ? "var(--tv-up)" : change < 0
    ? "var(--tv-down)" : "var(--tv-muted)";
  const stampMs = state.data.time[i];
  if (stampMs === undefined) {
    return;
  }
  const colour = (value: number): string => {
    const previous = i > 0 ? (state.data!.close[i - 1] ?? value) : value;
    const own = value - previous;
    return own > 0 ? "var(--tv-up)" : own < 0 ? "var(--tv-down)"
      : "var(--tv-muted)";
  };
  const open = state.data.open[i] ?? close;
  const high = state.data.high[i] ?? close;
  const low = state.data.low[i] ?? close;
  const stampedVolume = state.data.volume[i] ?? Number.NaN;

  const volumeHtml = withVolume && state.volumeShown
    ? `<span class="tv-legend__field">V <b>` +
      `${formatVolume(stampedVolume)}</b></span>`
    : "";
  legendEl.innerHTML =
    `<span class="tv-legend__stamp">` +
    karachiStamp.format(new Date(stampMs)) +
    ` <span class="tv-legend__day">` +
    karachiDay.format(new Date(stampMs)) + `</span></span>` +
    `<span class="tv-legend__field">O <b style="color:${colour(open)}">` +
    `${formatPrice(open, 2)}</b></span>` +
    `<span class="tv-legend__field">H <b style="color:${colour(high)}">` +
    `${formatPrice(high, 2)}</b></span>` +
    `<span class="tv-legend__field">L <b style="color:${colour(low)}">` +
    `${formatPrice(low, 2)}</b></span>` +
    `<span class="tv-legend__field">C <b style="color:${colour(close)}">` +
    `${formatPrice(close, 2)}</b></span>` +
    `<span class="tv-legend__field" style="color:${tone}">` +
    `${change >= 0 ? "+" : ""}${formatPrice(change, 2)} ` +
    `(${change >= 0 ? "+" : ""}${changePct.toFixed(2)}%)</span>` +
    volumeHtml;
}

// ---------------------------------------------------------------------------
// Live-shape paint: the mid-drag line, through the kept painter.
// ---------------------------------------------------------------------------

function paintOne(
  context: CanvasRenderingContext2D,
  chart: ReturnType<typeof createChart>,
  candles: ISeriesApi<"Candlestick", Time>,
  frame: ReturnType<typeof frameFor>,
  shape: Drawing,
): void {
  // The live shape draws through the same painter as the kept ones.
  paintOverlay(context, chart, candles, frame, {
    drawings: [shape],
    hidden: false,
    toolColor: "#2962ff",
    midDrag: null,
  });
}

// ---------------------------------------------------------------------------
// Indicator panes
// ---------------------------------------------------------------------------

/**
 * The indicators, on the chart the TV way: an overlay indicator paints on
 * the price pane, a pane indicator owns its own pane beneath the volume,
 * the first one starting at pane 2 (0 price, 1 volume). This runs on a
 * freshly built engine or on new bars; series then exist once and feed.
 */
function buildIndicators(
  state: EngineState,
  specs: readonly IndicatorSpec[],
  data: SeriesData,
  tokens: TvTheme,
): void {
  void tokens;
  const outputs = computeIndicators(specs, data);
  // Pane 0 is the price (volume rides its own overlay scale), so the first
  // study pane is pane 1.
  let nextPane = 1;
  for (const output of outputs) {
    if (output.error !== undefined) {
      continue;
    }
    const isPane = output.placement === "pane";
    const existing = state.panes.get(output.id);
    if (existing !== undefined) {
      for (let li = 0; li < output.lines.length && li < existing.lines.length; li += 1) {
        const priorLine = existing.lines[li];
        const nextLine = output.lines[li];
        if (priorLine !== undefined && nextLine !== undefined) {
          priorLine.setData(lineData(data, nextLine.values));
        }
      }
      if (existing.histogram !== undefined && output.histogram !== undefined) {
        existing.histogram.setData(histData(data, output));
      }
      continue;
    }

    const paneIndex = isPane ? nextPane : 0;
    if (isPane) {
      // Every study pane shares the height left under the price pane, never
      // the price pane's own share.
      state.chart.addPane().setStretchFactor(1);
      nextPane += 1;
    }
    const    lines: ISeriesApi<"Line", Time>[] = [];
    for (const line of output.lines) {
      const points = lineData(data, line.values);
      if (points.length === 0) {
        continue;
      }
      const lineSeries = state.chart.addSeries(LineSeries, {
        color: line.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: isPane && output.lines.length === 1,
      }, paneIndex);
      lineSeries.setData(points);
      fixRange(lineSeries, output.range);
      lines.push(lineSeries);
    }
    let histogram: ISeriesApi<"Histogram", Time> | undefined;
    if (output.histogram !== undefined) {
      const bars = histData(data, output);
      if (bars.length > 0) {
        histogram = state.chart.addSeries(HistogramSeries, {
          priceLineVisible: false,
          lastValueVisible: false,
        }, paneIndex);
        histogram.setData(bars);
        fixRange(histogram, output.range);
      }
    }
    const ref: PaneRef = histogram === undefined
      ? { lines }
      : { lines, histogram };
    state.panes.set(output.id, ref);
  }
}

/** A fixed indicator range (RSI 0-100) pins its pane's scale. */
function fixRange(    series: ISeriesApi<"Line", Time> | ISeriesApi<"Histogram", Time>,
  range: readonly [number, number] | null | undefined,
): void {
  if (range === undefined || range === null) {
    return;
  }
  (series as unknown as ISeriesApi<"Line", Time>).applyOptions({
    autoscaleInfoProvider: () => ({
      priceRange: {
        minValue: range[0],
        maxValue: range[1],
      },
    }),
  });
}

function lineData(data: SeriesData, values: Float64Array): LineData[] {
  const length = Math.min(data.time.length, values.length);
  const points: LineData[] = [];
  for (let i = 0; i < length; i += 1) {
    const value = values[i];
    const t = data.time[i];
    if (value === undefined || t === undefined || !Number.isFinite(value)) {
      continue; // the warm-up bars an indicator does not have yet
    }
    points.push({ time: (t / 1000) as UTCTimestamp, value });
  }
  return points;
}

function histData(
  data: SeriesData,
  output: IndicatorOutput,
): HistogramData[] {
  const histogram = output.histogram;
  if (histogram === undefined) {
    return [];
  }
  const length = Math.min(data.time.length, histogram.values.length);
  const points: HistogramData[] = [];
  for (let i = 0; i < length; i += 1) {
    const value = histogram.values[i];
    const t = data.time[i];
    if (value === undefined || t === undefined || !Number.isFinite(value)) {
      continue;
    }
    points.push({
      time: (t / 1000) as UTCTimestamp,
      value,
      color: value >= 0 ? histogram.positive : histogram.negative,
    });
  }
  return points;
}

// ---------------------------------------------------------------------------
// The order tape, TV-styled
// ---------------------------------------------------------------------------

/**
 * The order tape: the venue's own counters and the newest prints, floating
 * over the chart. It draws when the tape has either prints or counters to
 * show, and nothing when it has neither - no empty box.
 */
function printTape(
  prints: readonly PrintEvent[] | undefined,
  printTotals: PrintTotals | null | undefined,
): React.ReactNode {
  const hasPrints = prints !== undefined && prints.length > 0;
  const hasCounters = printTotals != null
    && [printTotals.buy_volume, printTotals.sell_volume,
        printTotals.volume, printTotals.orders]
      .some((value) =>
        value !== null && Number.isFinite(value) && value > 0);
  if (!hasPrints && !hasCounters) {
    return null;
  }
  return (
    <div className="chart__tape" aria-label="order tape, newest first">
      <div className="chart__tape__head">order tape</div>
      {printTotals != null ? (
        <div className="chart__tape__totals">
          {printTotals.buy_volume !== null
            && Number.isFinite(printTotals.buy_volume)
            && printTotals.buy_volume > 0
            ? (
              <span className="chart__tape__buy">
                buy {formatVolume(printTotals.buy_volume)}
              </span>
            )
            : null}
          {printTotals.sell_volume !== null
            && Number.isFinite(printTotals.sell_volume)
            && printTotals.sell_volume > 0
            ? (
              <span className="chart__tape__sell">
                sell {formatVolume(printTotals.sell_volume)}
              </span>
            )
            : null}
          {printTotals.volume !== null && Number.isFinite(printTotals.volume)
            ? (
              <span className="chart__tape__vol">
                vol {formatVolume(printTotals.volume)}
              </span>
            )
            : null}
          {printTotals.orders !== null && Number.isFinite(printTotals.orders)
            ? (
              <span className="chart__tape__orders">
                {formatVolume(printTotals.orders)} orders
              </span>
            )
            : null}
        </div>
      ) : null}
      {(prints ?? []).slice(-TAPE_ROWS).reverse().map((row, index) => {
        const sideClass = row.side === "B"
          ? " chart__tape__row--buy"
          : row.side === "S"
            ? " chart__tape__row--sell"
            : "";
        return (
          <div
            key={`${row.t}:${index}`}
            className={`chart__tape__row${sideClass}`}
          >
            <span className="chart__tape__time">{formatClock(row.t)}</span>
            <span className="chart__tape__price">{formatPrice(row.price)}</span>
            <span className="chart__tape__size">
              {row.size !== null && Number.isFinite(row.size)
                ? formatVolume(row.size)
                : ""}
            </span>
            <span className="chart__tape__side">
              {row.side === "B" ? "buy" : row.side === "S" ? "sell" : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
