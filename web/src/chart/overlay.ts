/**
 * The drawing overlay: shapes a reader places over the price pane.
 *
 * The overlay is an ordinary canvas filling the chart surface; the shapes
 * inside it are placed with the engine's own mappings (time → x, price →
 * y), so a drawing glued to a bar stays glued when the reader pans, zooms
 * or the next bars arrive. A drawing the viewport left is simply not
 * drawn this frame - the engine's timeToCoordinate answers null there.
 */

import type {
  IChartApi,
  ISeriesApi,
} from "lightweight-charts";

import {
  type AnchoredPoint,
  type Drawing,
  type MeasureResult,
} from "./drawings";

export interface DrawingChip {
  /** Drawing colour, TV's active blue. */
  color: string;
}

/** The pixels a shape may use: the price pane inside the axes. */
export interface OverlayFrame {
  /** Width of the price plot (the price axis is excluded). */
  readonly plotWidth: number;
  /** Height of pane 0, the price pane itself. */
  readonly plotHeight: number;
}

/** The measurements of the surface the overlay draws on. */
export function frameFor(chart: IChartApi, width: number, height: number):
  OverlayFrame {
  let axisWidth = 60;
  try {
    axisWidth = Math.max(0, Math.round(chart.priceScale("right").width()));
  } catch {
    axisWidth = 60;
  }
  let paneHeight = height;
  try {
    const paneArray = chart.panes();
    const first = paneArray[0];
    if (first !== undefined && typeof first.getHeight === "function") {
      const shown = first.getHeight();
      if (Number.isFinite(shown) && shown > 0) {
        paneHeight = Math.min(height, shown);
      }
    }
  } catch {
    // Older panes API: fall back to the whole height.
  }
  return {
    plotWidth: Math.max(0, width - axisWidth),
    plotHeight: Math.max(0, paneHeight),
  };
}

/** An anchor back into the tape's coordinates: the instant and the price. */
export function anchorAt(
  chart: IChartApi,
  candles: ISeriesApi<"Candlestick">,
  x: number,
  y: number,
): AnchoredPoint | null {
  const time = chart.timeScale().coordinateToTime(x);
  const price = candles.coordinateToPrice(y);
  if (time === null || price === null) {
    return null;
  }
  return { t: Number(time) * 1000, price };
}

/** Pixel coordinates of an anchor, or null when it is off the viewport. */
export function pixelAt(
  chart: IChartApi,
  candles: ISeriesApi<"Candlestick">,
  point: AnchoredPoint,
): { x: number; y: number } | null {
  const timeScale = chart.timeScale();
  const x = timeScale.timeToCoordinate((point.t / 1000) as never);
  const y = candles.priceToCoordinate(point.price);
  if (x === null || y === null) {
    return null;
  }
  return { x, y };
}

export interface OverlayShapeInput {
  readonly drawings: readonly Drawing[];
  readonly hidden: boolean;
  readonly toolColor: string;
  readonly midDrag: MeasureResult | null;
}

/**
 * Paint one frame: every kept drawing, then the live one mid-drag.
 * context/globalAlpha are the caller's; this must not touch state.
 */
export function paintOverlay(
  context: CanvasRenderingContext2D,
  chart: IChartApi,
  candles: ISeriesApi<"Candlestick">,
  frame: OverlayFrame,
  input: OverlayShapeInput,
): void {
  context.clearRect(0, 0, context.canvas.width, context.canvas.height);
  if (input.hidden && input.midDrag === null) {
    return;
  }
  const lineWidth = 1.6;
  for (const drawing of input.drawings) {
    if (input.hidden) {
      continue;
    }
    paintDrawing(context, chart, candles, frame, drawing,
      input.toolColor, lineWidth);
  }
  if (input.midDrag !== null) {
    paintMeasure(context, chart, candles, input.midDrag, input.toolColor);
  }
}

function paintDrawing(
  context: CanvasRenderingContext2D,
  chart: IChartApi,
  candles: ISeriesApi<"Candlestick">,
  frame: OverlayFrame,
  drawing: Drawing,
  color: string,
  lineWidth: number,
): void {
  const a = drawing.points[0];
  const b = drawing.points[1];
  if (a === undefined) {
    return;
  }
  context.beginPath();
  if (drawing.kind === "hline") {
    context.moveTo(0, mapY(candles, a.price));
    context.lineTo(frame.plotWidth, mapY(candles, a.price));
  } else if (drawing.kind === "hray") {
    const start = mapX(chart, a.t);
    if (start === null) {
      context.strokeStyle = color;
      context.lineWidth = lineWidth;
      context.stroke();
      return;
    }
    context.moveTo(start, mapY(candles, a.price));
    context.lineTo(frame.plotWidth, mapY(candles, a.price));
  } else {
    if (b === null) {
      return;
    }
    if (drawing.kind === "trend") {
      const p1 = pixelAt(chart, candles, a);
      const p2 = pixelAt(chart, candles, b);
      if (p1 === null || p2 === null) {
        return;
      }
      context.moveTo(p1.x, p1.y);
      context.lineTo(p2.x, p2.y);
    } else {
      // flatTop / flatBottom: a level held between two instants.
      const y = mapY(candles, a.price);
      const x1 = mapX(chart, a.t);
      const x2 = mapX(chart, b.t);
      if (x1 === null || x2 === null) {
        return;
      }
      context.moveTo(x1, y);
      context.lineTo(x2, y);
      paintEndCert(context, x1, y);
      paintEndCert(context, x2, y);
    }
  }
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.stroke();
}

function paintEndCert(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
): void {
  context.fillStyle = "rgba(41, 98, 255, 0.9)";
  context.beginPath();
  context.arc(x, y, 1.6, 0, Math.PI * 2);
  context.fill();
}

function mapX(chart: IChartApi, tMs: number): number | null {
  return chart.timeScale().timeToCoordinate((tMs / 1000) as never);
}

function mapY(candles: ISeriesApi<"Candlestick">, price: number): number {
  return candles.priceToCoordinate(price) ?? 0;
}

/** The measure readout, TV's dashed rectangle with the counting label. */
function paintMeasure(
  context: CanvasRenderingContext2D,
  chart: IChartApi,
  candles: ISeriesApi<"Candlestick">,
  midDrag: MeasureResult,
  color: string,
): void {
  const p1 = pixelAt(chart, candles, midDrag.from);
  const p2 = pixelAt(chart, candles, midDrag.to);
  if (p1 === null || p2 === null) {
    return;
  }
  const left = Math.min(p1.x, p2.x);
  const right = Math.max(p1.x, p2.x);
  const top = Math.min(p1.y, p2.y);
  const bottom = Math.max(p1.y, p2.y);

  context.save();
  context.setLineDash([4, 3]);
  context.strokeStyle = color;
  context.lineWidth = 1;
  context.fillStyle = "rgba(41, 98, 255, 0.12)";
  context.fillRect(left, top, Math.max(1, right - left),
    Math.max(1, bottom - top));
  context.strokeRect(left, top, Math.max(1, right - left),
    Math.max(1, bottom - top));

  const tone = midDrag.up === true ? "#089981" : midDrag.up === false
    ? "#f23645" : "#787b86";
  const label =
    `${midDrag.delta >= 0 ? "+" : ""}${midDrag.delta.toFixed(2)} ` +
    `(${midDrag.pct >= 0 ? "+" : ""}${midDrag.pct.toFixed(2)}%)`;
  const bars = `${Math.round(midDrag.minutes / 1)} m`;
  context.setLineDash([]);
  context.font = "11px 'Trebuchet MS', sans-serif";
  const textWidth = context.measureText(label).width;
  const boxWidth = textWidth + 12;
  const boxHeight = 18;
  const boxX = Math.min(right, boxWidth) - boxWidth;
  const boxY = bottom + 2;
  context.fillStyle = "rgba(19, 23, 34, 0.92)";
  context.fillRect(boxX, boxY, boxWidth, boxHeight + 14);
  context.fillStyle = tone;
  context.textAlign = "left";
  context.fillText(label, boxX + 6, boxY + 12);
  context.fillStyle = "#787b86";
  context.font = "10px 'Trebuchet MS', sans-serif";
  context.fillText(bars, boxX + 6, boxY + 26);
  context.restore();
}
