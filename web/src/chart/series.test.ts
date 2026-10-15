/**
 * The series store, which is the one place where a wrong assumption about
 * bar ordering or aggregation would corrupt every pixel on the chart.
 */

import { describe, expect, it } from "vitest";

import type { Bar } from "../api/types";
import {
  bucketFor,
  ColumnSeries,
  gapsInWindow,
  timeMs,
} from "./series";

const BASE = "2026-10-12T09:32:00+05:00";

function bar(minute: number, close: number, volume = 100): Bar {
  const moment = new Date(timeMs(BASE) + minute * 60_000).toISOString();
  return {
    t: moment,
    o: close - 0.5,
    h: close + 1,
    l: close - 1.5,
    c: close,
    v: volume,
  };
}

function seriesOf(count: number): ColumnSeries {
  const series = new ColumnSeries(4);
  series.upsertMany(
    Array.from({ length: count }, (_, index) => bar(index, 100 + index)),
  );
  return series;
}

describe("ColumnSeries", () => {
  it("appends bars in order and reads them back", () => {
    const series = seriesOf(3);
    expect(series.length).toBe(3);
    expect(series.at(0)?.c).toBe(100);
    expect(series.at(2)?.c).toBe(102);
    expect(series.at(3)).toBeUndefined();
  });

  it("replaces the minute that is still forming", () => {
    const series = seriesOf(2);
    const outcome = series.upsert(bar(1, 155));
    expect(outcome).toBe("revised");
    expect(series.length).toBe(2);
    expect(series.at(1)?.c).toBe(155);
    expect(series.revisionCount).toBe(1);
  });

  it("ignores an identical republish", () => {
    const series = seriesOf(2);
    expect(series.upsert(bar(1, 101))).toBe("ignored");
    expect(series.revisionCount).toBe(0);
  });

  it("inserts an out of order bar in the right place", () => {
    const series = seriesOf(3);
    const missing = bar(1, 999);
    const without = new ColumnSeries();
    without.upsertMany([bar(0, 100), bar(2, 102)]);
    expect(without.upsert(missing)).toBe("appended");
    expect(without.length).toBe(3);
    const stamps = [0, 1, 2].map((index) => without.at(index)?.c);
    expect(stamps).toEqual([100, 999, 102]);
    // The original series is untouched by the other one's work.
    expect(series.at(1)?.c).toBe(101);
  });

  it("grows past its initial capacity", () => {
    const series = seriesOf(50);
    expect(series.length).toBe(50);
    expect(series.at(49)?.c).toBe(149);
  });

  it("counts appended and revised bars separately", () => {
    const series = seriesOf(2);
    const counts = series.upsertMany([bar(1, 500), bar(2, 200)]);
    expect(counts).toEqual({ appended: 1, revised: 1 });
  });

  it("finds the window that covers a span", () => {
    const series = seriesOf(10);
    const from = timeMs(BASE) + 2 * 60_000;
    const to = timeMs(BASE) + 5 * 60_000;
    const window = series.window(from, to);
    expect(window.from).toBe(2);
    expect(window.to).toBe(5);
  });

  it("clamps a window that starts before the series", () => {
    const series = seriesOf(4);
    const window = series.window(timeMs(BASE) - 600_000, timeMs(BASE));
    expect(window.from).toBe(0);
    expect(window.to).toBe(0);
  });

  it("measures a price range and a volume range over a window", () => {
    const series = seriesOf(5);
    const range = series.priceRange(1, 3);
    expect(range.min).toBeCloseTo(99.5, 6);
    expect(range.max).toBeCloseTo(104, 6);
    expect(series.maxVolume(0, 4)).toBe(100);
  });

  it("returns a safe range for an empty window", () => {
    const series = seriesOf(3);
    expect(series.priceRange(0, 2)).toEqual({ min: 98.5, max: 103 });
    const empty = new ColumnSeries();
    expect(empty.priceRange(0, 0)).toEqual({ min: 0, max: 1 });
    expect(empty.maxVolume(0, 0)).toBe(0);
  });

  it("folds bars into buckets with the exchange's own OHLC rules", () => {
    const series = new ColumnSeries();
    series.upsertMany([
      bar(0, 100, 10),
      bar(1, 102, 20),
      bar(2, 98, 30),
      bar(5, 110, 40),
    ]);
    // A five minute bucket: the first three minutes fold into one bar.
    const folded = series.aggregate(5 * 60_000);
    expect(folded.length).toBe(2);
    const first = folded.at(0);
    expect(first?.o).toBe(99.5);
    expect(first?.h).toBe(103);
    expect(first?.l).toBe(96.5);
    expect(first?.c).toBe(98);
    expect(first?.v).toBe(60);
    expect(folded.at(1)?.v).toBe(40);
  });

  it("leaves the underlying series alone when it aggregates", () => {
    const series = seriesOf(4);
    series.aggregate(10 * 60_000);
    expect(series.length).toBe(4);
  });

  it("clears everything on demand", () => {
    const series = seriesOf(3);
    series.clear();
    expect(series.length).toBe(0);
    expect(series.at(0)).toBeUndefined();
    expect(series.revisionCount).toBe(0);
  });

  it("ignores a bar whose timestamp cannot be parsed", () => {
    const series = new ColumnSeries();
    expect(series.upsert({ t: "not a date", o: 1, h: 2, l: 0.5, c: 1, v: 0 }))
      .toBe("ignored");
    expect(series.length).toBe(0);
  });
});

describe("bucketFor", () => {
  it("keeps the base interval when there is room", () => {
    expect(bucketFor(60_000 * 10, 900)).toBe(60_000);
  });

  it("rounds up to whole minutes when the span is long", () => {
    const bucket = bucketFor(60_000 * 240, 300);
    expect(bucket % 60_000).toBe(0);
    expect(bucket).toBeGreaterThan(60_000);
  });

  it("is defensive about nonsense input", () => {
    expect(bucketFor(0, 0)).toBe(60_000);
    expect(bucketFor(-1, 100)).toBe(60_000);
  });
});

describe("gapsInWindow", () => {
  it("keeps only the gaps that intersect the window", () => {
    const gaps = [
      {
        start: "2026-10-12T09:36:00+05:00",
        end: "2026-10-12T09:37:00+05:00",
        minutes: 2,
        reason: "no bar was printed in this minute",
      },
      {
        start: "2026-10-12T14:00:00+05:00",
        end: "2026-10-12T14:05:00+05:00",
        minutes: 6,
        reason: "no bar was printed in this minute",
      },
    ];
    const kept = gapsInWindow(gaps, timeMs(BASE), timeMs(BASE) + 10 * 60_000);
    expect(kept.length).toBe(1);
    expect(kept[0]?.minutes).toBe(2);
  });
});
