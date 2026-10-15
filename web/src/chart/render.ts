/**
 * The canvas renderer.
 *
 * One function draws one frame. It reads a window of the series, decides the
 * candle width from the space actually available, and paints. It never
 * touches React state, never allocates per bar, and never draws a candle
 * outside the plot: that is what keeps a live chart at frame rate while bars
 * keep arriving.
 *
 * The two honesty features the server asked for are drawn literally:
 * measured gaps are shaded across the plot with their minute count, and an
 * empty window says "no bars for this symbol yet" on the canvas rather than
 * showing an empty price axis that could be mistaken for a flat market.
 */

import type { Gap } from "../api/types";
import { formatClock, formatDay, formatPrice, formatVolume } from "./format";
import { decimalsFor, linearScale, niceTicks } from "./scale";
import { type ColumnSeries, gapsInWindow, timeMs } from "./series";

export interface RendererTheme {
  readonly background: string;
  readonly grid: string;
  readonly axisText: string;
  readonly up: string;
  readonly down: string;
  readonly volumeUp: string;
  readonly volumeDown: string;
  readonly gapFill: string;
  readonly gapText: string;
  readonly crosshair: string;
  readonly lastLine: string;
  readonly muted: string;
}

export const DARK_THEME: RendererTheme = {
  background: "#0e1116",
  grid: "#1c2330",
  axisText: "#8b98ab",
  up: "#2fbf71",
  down: "#e05252",
  volumeUp: "rgba(47, 191, 113, 0.35)",
  volumeDown: "rgba(224, 82, 82, 0.35)",
  gapFill: "rgba(139, 152, 171, 0.10)",
  gapText: "rgba(139, 152, 171, 0.75)",
  crosshair: "#5b6474",
  lastLine: "#8b98ab",
  muted: "#8b98ab",
};

export interface ChartGeometry {
  readonly plotLeft: number;
  readonly plotRight: number;
  readonly plotTop: number;
  readonly plotBottom: number;
  readonly volumeTop: number;
  readonly priceAxisWidth: number;
  readonly timeAxisHeight: number;
}

export function geometryFor(width: number, height: number): ChartGeometry {
  const priceAxisWidth = 62;
  const timeAxisHeight = 20;
  const padding = 6;
  const plotBottom = Math.max(padding, height - timeAxisHeight);
  const plotTop = padding;
  return {
    plotLeft: padding,
    plotRight: Math.max(padding + 10, width - priceAxisWidth),
    plotTop,
    plotBottom,
    volumeTop: plotBottom - Math.min(90, (plotBottom - plotTop) * 0.22),
    priceAxisWidth,
    timeAxisHeight,
  };
}

export interface Crosshair {
  readonly index: number;
  readonly x: number;
  readonly y: number;
}

export interface RenderInput {
  readonly series: ColumnSeries;
  readonly gaps: readonly Gap[];
  readonly fromMs: number;
  readonly toMs: number;
  readonly width: number;
  readonly height: number;
  readonly dpr: number;
  readonly crosshair?: Crosshair | null;
  readonly theme?: RendererTheme;
}

export function drawChart(
  context: CanvasRenderingContext2D,
  input: RenderInput,
): void {
  const theme = input.theme ?? DARK_THEME;
  const { width, height, dpr } = input;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, width, height);
  context.fillStyle = theme.background;
  context.fillRect(0, 0, width, height);

  const frame = geometryFor(width, height);
  const plotWidth = frame.plotRight - frame.plotLeft;
  if (plotWidth <= 10) {
    return;
  }

  const { series } = input;
  const window = series.window(input.fromMs, input.toMs);
  const visible = window.to - window.from + 1;
  const timeScale = linearScale([input.fromMs, input.toMs],
    [frame.plotLeft, frame.plotRight]);

  drawGaps(context, input, frame, timeScale, theme);

  if (series.length === 0 || visible <= 0) {
    context.fillStyle = theme.muted;
    context.font = "13px ui-sans-serif, system-ui, sans-serif";
    context.textAlign = "center";
    context.fillText("no bars for this symbol yet",
      frame.plotLeft + plotWidth / 2, frame.plotTop + (frame.plotBottom - frame.plotTop) / 2);
    drawTimeAxis(context, input, frame, theme);
    context.textAlign = "left";
    return;
  }

  const prices = series.priceRange(window.from, window.to);
  const pad = (prices.max - prices.min || Math.max(0.01, prices.max * 0.01)) * 0.08;
  const priceScale = linearScale([prices.min - pad, prices.max + pad],
    [frame.plotBottom, frame.plotTop]);
  const volumeMax = series.maxVolume(window.from, window.to);

  drawPriceGrid(context, frame, priceScale, prices, pad, theme);
  drawTimeAxis(context, input, frame, theme);
  drawVolume(context, input, frame, window, timeScale, volumeMax, theme);
  drawCandles(context, input, frame, window, timeScale, priceScale, theme);
  drawLastPrice(context, input, frame, priceScale, window, theme);

  if (input.crosshair) {
    drawCrosshair(context, input, frame, priceScale, theme, input.crosshair);
  }
}

// ------------------------------------------------------------------ pieces

function drawPriceGrid(
  context: CanvasRenderingContext2D,
  frame: ChartGeometry,
  priceScale: (value: number) => number,
  prices: { min: number; max: number },
  pad: number,
  theme: RendererTheme,
): void {
  const ticks = niceTicks(prices.min - pad, prices.max + pad, 6);
  const decimals = decimalsFor(ticks.step);
  context.font = "11px ui-sans-serif, system-ui, sans-serif";
  context.textAlign = "left";
  context.textBaseline = "middle";
  for (const value of ticks.values) {
    const y = Math.round(priceScale(value)) + 0.5;
    context.strokeStyle = theme.grid;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(frame.plotLeft, y);
    context.lineTo(frame.plotRight, y);
    context.stroke();
    context.fillStyle = theme.axisText;
    context.fillText(formatPrice(value, decimals), frame.plotRight + 6, y);
  }
}

function drawTimeAxis(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  theme: RendererTheme,
): void {
  const labels = 6;
  const spanMs = input.toMs - input.fromMs;
  const crossesDay = formatDay(new Date(input.fromMs).toISOString()) !==
    formatDay(new Date(input.toMs).toISOString());
  context.font = "11px ui-sans-serif, system-ui, sans-serif";
  context.fillStyle = theme.axisText;
  context.textAlign = "center";
  context.textBaseline = "top";
  for (let step = 0; step <= labels; step += 1) {
    const moment = input.fromMs + (spanMs * step) / labels;
    const x = frame.plotLeft + ((frame.plotRight - frame.plotLeft) * step) / labels;
    const iso = new Date(moment).toISOString();
    const text = crossesDay && step === 0
      ? `${formatDay(iso)} ${formatClock(iso)}`
      : formatClock(iso);
    const width = context.measureText(text).width;
    const clamped = Math.min(
      frame.plotRight - width / 2,
      Math.max(frame.plotLeft + width / 2, x),
    );
    context.fillText(text, clamped, frame.plotBottom + 4);
  }
  context.textAlign = "left";
  context.textBaseline = "alphabetic";
}

function drawGaps(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  timeScale: (value: number) => number,
  theme: RendererTheme,
): void {
  const gaps = gapsInWindow(input.gaps, input.fromMs, input.toMs);
  if (gaps.length === 0) {
    return;
  }
  context.font = "10px ui-sans-serif, system-ui, sans-serif";
  for (const gap of gaps) {
    const left = timeScale(timeMs(gap.start));
    const right = timeScale(timeMs(gap.end) + 60_000);
    const width = Math.max(2, right - left);
    context.fillStyle = theme.gapFill;
    context.fillRect(left, frame.plotTop, width, frame.plotBottom - frame.plotTop);
    if (width > 34) {
      context.fillStyle = theme.gapText;
      context.textAlign = "left";
      context.fillText(`${Math.round(gap.minutes)}m gap`, left + 3, frame.plotTop + 10);
    }
  }
  context.textAlign = "left";
}

function drawCandles(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  window: { from: number; to: number },
  timeScale: (value: number) => number,
  priceScale: (value: number) => number,
  theme: RendererTheme,
): void {
  const visible = window.to - window.from + 1;
  const slot = (frame.plotRight - frame.plotLeft) / Math.max(1, visible);
  const bodyWidth = Math.max(1, Math.min(14, slot * 0.7));
  const half = bodyWidth / 2;
  for (let index = window.from; index <= window.to; index += 1) {
    const bar = input.series.at(index);
    if (bar === undefined) {
      continue;
    }
    const rising = bar.c >= bar.o;
    const colour = rising ? theme.up : theme.down;
    const x = timeScale(bar.timeMs) + slot / 2;
    context.strokeStyle = colour;
    context.fillStyle = colour;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(Math.round(x) + 0.5, priceScale(bar.h));
    context.lineTo(Math.round(x) + 0.5, priceScale(bar.l));
    context.stroke();
    const top = priceScale(Math.max(bar.o, bar.c));
    const bottom = priceScale(Math.min(bar.o, bar.c));
    const height = Math.max(1, bottom - top);
    context.fillRect(x - half, top, bodyWidth, height);
  }
}

function drawVolume(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  window: { from: number; to: number },
  timeScale: (value: number) => number,
  volumeMax: number,
  theme: RendererTheme,
): void {
  if (volumeMax <= 0) {
    return;
  }
  const visible = window.to - window.from + 1;
  const slot = (frame.plotRight - frame.plotLeft) / Math.max(1, visible);
  const bodyWidth = Math.max(1, Math.min(14, slot * 0.7));
  const height = frame.plotBottom - frame.volumeTop;
  for (let index = window.from; index <= window.to; index += 1) {
    const bar = input.series.at(index);
    if (bar === undefined) {
      continue;
    }
    const scale = bar.v / volumeMax;
    const barHeight = Math.max(0.5, height * scale);
    const x = timeScale(bar.timeMs) + slot / 2;
    context.fillStyle = bar.c >= bar.o ? theme.volumeUp : theme.volumeDown;
    context.fillRect(x - bodyWidth / 2, frame.plotBottom - barHeight,
      bodyWidth, barHeight);
  }
}

function drawLastPrice(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  priceScale: (value: number) => number,
  window: { from: number; to: number },
  theme: RendererTheme,
): void {
  const last = input.series.at(window.to);
  if (last === undefined) {
    return;
  }
  const y = Math.round(priceScale(last.c)) + 0.5;
  context.save();
  context.setLineDash([4, 4]);
  context.strokeStyle = theme.lastLine;
  context.beginPath();
  context.moveTo(frame.plotLeft, y);
  context.lineTo(frame.plotRight, y);
  context.stroke();
  context.restore();

  const label = formatPrice(last.c, 2);
  context.font = "11px ui-sans-serif, system-ui, sans-serif";
  const width = context.measureText(label).width + 10;
  context.fillStyle = last.c >= last.o ? theme.up : theme.down;
  context.fillRect(frame.plotRight + 2, y - 8, width, 16);
  context.fillStyle = "#0e1116";
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillText(label, frame.plotRight + 7, y);
  context.textBaseline = "alphabetic";
}

function drawCrosshair(
  context: CanvasRenderingContext2D,
  input: RenderInput,
  frame: ChartGeometry,
  priceScale: (value: number) => number,
  theme: RendererTheme,
  crosshair: Crosshair,
): void {
  const bar = input.series.at(crosshair.index);
  if (bar === undefined) {
    return;
  }
  context.save();
  context.strokeStyle = theme.crosshair;
  context.lineWidth = 1;
  context.setLineDash([3, 3]);
  context.beginPath();
  context.moveTo(Math.round(crosshair.x) + 0.5, frame.plotTop);
  context.lineTo(Math.round(crosshair.x) + 0.5, frame.plotBottom);
  context.moveTo(frame.plotLeft, Math.round(crosshair.y) + 0.5);
  context.lineTo(frame.plotRight, Math.round(crosshair.y) + 0.5);
  context.stroke();
  context.restore();

  const readout =
    `${formatClock(new Date(bar.timeMs).toISOString())}  ` +
    `O ${formatPrice(bar.o)}  H ${formatPrice(bar.h)}  ` +
    `L ${formatPrice(bar.l)}  C ${formatPrice(bar.c)}  V ${formatVolume(bar.v)}`;
  context.font = "11px ui-sans-serif, system-ui, sans-serif";
  const width = context.measureText(readout).width + 12;
  context.fillStyle = "rgba(14, 17, 22, 0.9)";
  context.fillRect(frame.plotLeft, frame.plotTop, width, 18);
  context.fillStyle = theme.axisText;
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillText(readout, frame.plotLeft + 6, frame.plotTop + 9);
  context.textBaseline = "alphabetic";

  // The price under the pointer, on the same axis the candles use.
  const pointerPrice = priceFromY(priceScale, crosshair.y, frame);
  if (pointerPrice !== null) {
    context.fillStyle = theme.crosshair;
    context.fillRect(frame.plotRight + 2, crosshair.y - 8,
      frame.priceAxisWidth - 2, 16);
    context.fillStyle = "#0e1116";
    context.fillText(formatPrice(pointerPrice, 2), frame.plotRight + 6,
      crosshair.y);
  }
}

/** Invert a price scale for the pointer's y, clamped to the plot. */
function priceFromY(
  priceScale: (value: number) => number,
  y: number,
  frame: ChartGeometry,
): number | null {
  if (y < frame.plotTop || y > frame.plotBottom) {
    return null;
  }
  const domain = (priceScale as unknown as { domain?: readonly [number, number] })
    .domain;
  const range = (priceScale as unknown as { range?: readonly [number, number] })
    .range;
  if (domain === undefined || range === undefined) {
    return null;
  }
  const [d0, d1] = domain;
  const [r0, r1] = range;
  if (r1 === r0) {
    return null;
  }
  const ratio = (y - r0) / (r1 - r0);
  return d0 + ratio * (d1 - d0);
}
