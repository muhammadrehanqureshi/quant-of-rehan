/**
 * The series store, which is the one place where a wrong assumption about
 * bar ordering or aggregation would corrupt every pixel on the chart.
 */

import { describe, expect, it } from "vitest";

import type { Bar } from "../api/types";
import {
  bucketFor,
  ColumnSeries,
  displayBucket,
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

describe("displayBucket", () => {
  const DAY = 86_400_000;

  it("keeps minute candles when a holey window has room for every bar", () => {
    // The shape that made this necessary: 37 bars spread over 121 minutes by a
    // 73 minute hole, drawn 358 pixels wide. Sizing buckets by the 127 minute
    // span folded them into two minute candles although each bar had 9 pixels.
    expect(displayBucket(37, 60_000, 358)).toBe(60_000);
  });

  it("folds a crowded window into whole steps", () => {
    const bucket = displayBucket(2000, 60_000, 358);
    expect(bucket % 60_000).toBe(0);
    expect(bucket).toBeGreaterThan(60_000);
    expect(2000 * 60_000 / bucket).toBeLessThanOrEqual(358 / 3 + 1);
  });

  it("folds a daily series in whole days, not in minutes", () => {
    const bucket = displayBucket(240, DAY, 358);
    expect(bucket % DAY).toBe(0);
    expect(bucket).toBeGreaterThan(DAY);
  });

  it("never folds below one step, whatever it is given", () => {
    expect(displayBucket(0, 60_000, 0)).toBe(60_000);
    expect(displayBucket(-4, 60_000, -10)).toBe(60_000);
    expect(displayBucket(1, 0, 358)).toBe(60_000);
    expect(displayBucket(5, DAY, 358)).toBe(DAY);
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

describe("the viewport shape a series reports", () => {
  function filled(count: number, startMs = 1_700_000_000_000) {
    const series = new ColumnSeries(64);
    for (let index = 0; index < count; index += 1) {
      series.upsert({
        t: new Date(startMs + index * 60_000).toISOString(),
        o: 100 + index,
        h: 101 + index,
        l: 99 + index,
        c: 100.5 + index,
        v: 1000,
      });
    }
    return series;
  }

  it("reports nothing for an empty series", () => {
    expect(new ColumnSeries(8).bounds()).toBeNull();
  });

  it("reports the first bar, the last bar, the count and the step", () => {
    const bounds = filled(10).bounds();
    expect(bounds?.count).toBe(10);
    expect(bounds?.lastMs).toBe(1_700_000_000_000 + 9 * 60_000);
    expect(bounds?.stepMs).toBe(60_000);
  });

  it("assumes a minute for a single bar", () => {
    expect(filled(1).bounds()?.stepMs).toBe(60_000);
  });

  it("ignores a long hole when measuring the bar width", () => {
    // The real shape of an illiquid PSX minute series: a run of minutes, then
    // a long stretch with no print, then one more bar. The width is a minute.
    const series = new ColumnSeries(64);
    const start = 1_700_000_000_000;
    const push = (ms: number) =>
      series.upsert({ t: new Date(ms).toISOString(), o: 100, h: 101, l: 99,
                      c: 100, v: 10 });
    for (let index = 0; index < 40; index += 1) {
      push(start + index * 60_000);
    }
    push(start + (40 + 74) * 60_000);
    expect(series.bounds()?.stepMs).toBe(60_000);
  });

  it("measures an aggregated series by its own bucket", () => {
    const hourly = new ColumnSeries(16);
    const start = 1_700_000_000_000;
    for (let index = 0; index < 8; index += 1) {
      hourly.upsert({ t: new Date(start + index * 3_600_000).toISOString(),
                      o: 100, h: 101, l: 99, c: 100, v: 10 });
    }
    expect(hourly.bounds()?.stepMs).toBe(3_600_000);
  });

  it("counts the bars in a window without scanning them", () => {
    const series = filled(100);
    const start = 1_700_000_000_000;
    expect(series.countInWindow(start, start + 10 * 60_000)).toBe(10);
    expect(series.countInWindow(start + 10 * 60_000, start + 20 * 60_000)).toBe(10);
    expect(series.countInWindow(start - 60_000, start)).toBe(0);
  });

  it("counts nothing for an inverted window", () => {
    expect(filled(5).countInWindow(1_700_000_500_000, 1_700_000_000_000)).toBe(0);
  });

  it("reports how many bars a window holds of a short series", () => {
    const series = filled(3);
    const start = 1_700_000_000_000;
    expect(series.countInWindow(start, start + 60 * 60_000)).toBe(3);
  });
});
