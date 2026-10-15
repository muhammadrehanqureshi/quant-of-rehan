/**
 * The chart surface.
 *
 * The drawing rule that matters: React re-renders for metadata, the canvas
 * redraws imperatively from typed arrays. A pointer move updates a ref and
 * repaints, and it writes the readout through a DOM ref, so hovering never
 * re-renders the tree, and a burst of live bars never allocates a new series.
 */

import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";

import type { Gap } from "../api/types";
import { formatClock, formatPrice, formatVolume } from "../chart/format";
import { drawChart, type Crosshair, geometryFor } from "../chart/render";
import { bucketFor, type ColumnSeries } from "../chart/series";

/** How much of the series is on screen, in bars. */
const VISIBLE_BARS = 260;
const MIN_WIDTH = 320;
const MIN_HEIGHT = 220;

export interface ChartCanvasProps {
  readonly series: ColumnSeries;
  readonly gaps: readonly Gap[];
  readonly version: number;
}

interface Span {
  readonly fromMs: number;
  readonly toMs: number;
}

function visibleSpan(series: ColumnSeries, previous: Span | null): Span {
  const last = series.at(series.length - 1);
  if (last === undefined) {
    return previous ?? { fromMs: Date.now() - 3_600_000, toMs: Date.now() };
  }
  const count = Math.min(series.length, VISIBLE_BARS);
  const first = series.at(Math.max(0, series.length - count));
  const fallback = 60_000;
  return {
    fromMs: first?.timeMs ?? last.timeMs - fallback,
    toMs: last.timeMs + fallback,
  };
}

export function ChartCanvas({ series, gaps, version }: ChartCanvasProps) {
  const wrapper = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const crosshair = useRef<Crosshair | null>(null);
  const span = useRef<Span | null>(null);
  const folded = useRef<ColumnSeries | null>(null);
  const readout = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 320 });

  useEffect(() => {
    const node = wrapper.current;
    if (node === null) {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect === undefined) {
        return;
      }
      setSize({
        width: Math.max(MIN_WIDTH, Math.round(rect.width)),
        height: Math.max(MIN_HEIGHT, Math.round(rect.height)),
      });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const paint = useCallback(() => {
    const surface = canvas.current;
    if (surface === null) {
      return;
    }
    const context = surface.getContext("2d");
    if (context === null) {
      return;
    }
    const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
    if (surface.width !== Math.round(size.width * dpr) ||
        surface.height !== Math.round(size.height * dpr)) {
      surface.width = Math.round(size.width * dpr);
      surface.height = Math.round(size.height * dpr);
      surface.style.width = `${size.width}px`;
      surface.style.height = `${size.height}px`;
    }
    // The span is captured once and then held, so a bar arriving does not
    // slide the whole chart sideways while the reader is looking at it.
    span.current = visibleSpan(series, span.current);
    const view = span.current;
    const plotWidth = size.width - 70;
    const bucket = bucketFor(view.toMs - view.fromMs, plotWidth);
    const drawn = bucket > 60_000 ? series.aggregate(bucket) : series;
    folded.current = drawn;
    drawChart(context, {
      series: drawn,
      gaps,
      fromMs: view.fromMs,
      toMs: view.toMs,
      width: size.width,
      height: size.height,
      dpr,
      crosshair: crosshair.current,
    });
  }, [series, gaps, size]);

  useEffect(() => {
    paint();
  }, [paint, version]);

  const locate = useCallback(
    (clientX: number, clientY: number) => {
      const surface = canvas.current;
      const drawn = folded.current;
      const view = span.current;
      if (surface === null || drawn === null || view === null) {
        return null;
      }
      const rect = surface.getBoundingClientRect();
      const frame = geometryFor(size.width, size.height);
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      const ratio = (x - frame.plotLeft) / (frame.plotRight - frame.plotLeft);
      const moment = view.fromMs + ratio * (view.toMs - view.fromMs);
      const index = drawn.indexAtOrBefore(moment);
      if (index < 0) {
        return null;
      }
      return { index, x, y };
    },
    [size.height, size.width],
  );

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLCanvasElement>) => {
      const found = locate(event.clientX, event.clientY);
      if (found === null) {
        return;
      }
      crosshair.current = found;
      const bar = folded.current?.at(found.index);
      if (readout.current !== null && bar !== undefined) {
        readout.current.textContent =
          `${formatClock(new Date(bar.timeMs).toISOString())}  ` +
          `O ${formatPrice(bar.o)}  H ${formatPrice(bar.h)}  ` +
          `L ${formatPrice(bar.l)}  C ${formatPrice(bar.c)}  ` +
          `V ${formatVolume(bar.v)}`;
      }
      paint();
    },
    [locate, paint],
  );

  const onPointerLeave = useCallback(() => {
    crosshair.current = null;
    if (readout.current !== null) {
      readout.current.textContent = "";
    }
    paint();
  }, [paint]);

  return (
    <div className="chart" ref={wrapper}>
      <canvas
        ref={canvas}
        className="chart__canvas"
        onPointerMove={onPointerMove}
        onPointerLeave={onPointerLeave}
        role="img"
        aria-label={`price chart with ${series.length} bars`}
      />
      <div className="chart__readout" ref={readout} aria-live="off" />
      <div className="chart__hint">hover to read a bar</div>
    </div>
  );
}
