/**
 * The overlay's own math, detached from the canvas: the frame the price
 * pane gets from the engine's sizes, and the labels a measure carries.
 */

import { describe, expect, it } from "vitest";
import { frameFor, anchorAt, pixelAt } from "./overlay";

type Chartish = Parameters<typeof frameFor>[0];

function fakeChart(sizes: { axis?: number } = {}): Chartish {
  return {
    priceScale: () => ({
      width: () => sizes.axis ?? 60,
    }),
    panes: () => [],
  } as unknown as Chartish;
}

describe("overlay frame", () => {
  it("subtracts the price axis from the plot width", () => {
    const frame = frameFor(fakeChart({ axis: 60 }), 800, 500);
    expect(frame.plotWidth).toBe(740);
    expect(frame.plotHeight).toBe(500);
  });

  it("a chart that hides its sizes still yields a sane frame", () => {
    const broken = {
      priceScale: () => {
        throw new Error("no scale yet");
      },
      panes: () => [],
    } as unknown as Chartish;
    const frame = frameFor(broken, 800, 500);
    expect(frame.plotWidth).toBe(740);
  });

  it("pane 0 never borrows from the panes below it", () => {
    const paged = {
      priceScale: () => ({ width: () => 58 }),
      panes: () => [
        { getHeight: () => 360 },
        { getHeight: () => 110 },
      ],
    } as unknown as Chartish;
    const frame = frameFor(paged, 900, 520);
    expect(frame.plotHeight).toBe(360);
    expect(frame.plotWidth).toBe(842);
  });
});

describe("anchor mapping", () => {
  const chart = {
    timeScale: () => ({
      coordinateToTime: (x: number) =>
        x >= 0 && x <= 100 ? Math.floor(x * 1000) : null,
      // The engine's own second-scale: only seconds 0..100 are on screen.
      timeToCoordinate: (t: number) =>
        (t >= 0 && t <= 100 ? t : null),
    }),
  } as unknown as Parameters<typeof anchorAt>[0];
  const candles = {
    coordinateToPrice: (y: number) => (y >= 0 && y <= 200 ? 1000 - y / 2 : null),
    priceToCoordinate: (price: number) => (price >= 900 && price <= 1000
      ? (1000 - price) * 2
      : null),
  } as unknown as Parameters<typeof anchorAt>[1];

  it("a click anchors onto the tape's own instant and price", () => {
    expect(anchorAt(chart, candles, 40, 120))
      .toEqual({ t: 40_000_000, price: 940 });
  });

  it("a point outside the drawn panel anchors to nothing", () => {
    expect(anchorAt(chart, candles, -5, 10)).toBe(null);
    expect(anchorAt(chart, candles, 40, 900)).toBe(null);
  });

  it("an anchor off the viewport maps to no pixel", () => {
    expect(pixelAt(chart, candles, { t: 200_000, price: 950 })).toBe(null);
    expect(pixelAt(chart, candles, { t: 20_000, price: 850 })).toBe(null);
    expect(pixelAt(chart, candles, { t: 20_000, price: 950 }))
      .toEqual({ x: 20, y: 100 });
  });
});
