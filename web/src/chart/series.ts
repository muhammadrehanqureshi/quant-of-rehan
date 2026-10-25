/**
 * The client side series: columns, upserts, aggregation and windowing.
 *
 * The performance decision that matters for a live chart is here. A chart
 * redraws on every poll, so the data structure it reads must not allocate a
 * new array of objects per frame, and a zoomed out view must not draw ten
 * thousand candles into eight hundred pixels. So a series is stored as
 * parallel typed arrays, and `aggregate` folds consecutive bars into buckets
 * using the exchange's own OHLC rules: open from the first bar, high and low
 * from the extremes, close from the last, volume summed. That is the same
 * information at a resolution the screen can actually show.
 *
 * Upsert semantics match the server store exactly: a bar with a timestamp
 * that already exists replaces the row (the minute still forming), and an
 * identical republish is not a revision.
 */

import type { Bar, Gap } from "../api/types";

export interface BarRow {
  readonly timeMs: number;
  readonly o: number;
  readonly h: number;
  readonly l: number;
  readonly c: number;
  readonly v: number;
}

export interface UpsertCounts {
  readonly appended: number;
  readonly revised: number;
}

/** Parse a wire timestamp to epoch milliseconds, or NaN if unusable. */
export function timeMs(iso: string): number {
  return new Date(iso).getTime();
}

const INITIAL_CAPACITY = 1024;

export class ColumnSeries {
  private count = 0;
  private capacity: number;
  private time: Float64Array;
  private open: Float64Array;
  private high: Float64Array;
  private low: Float64Array;
  private close: Float64Array;
  private volume: Float64Array;
  private revisions = 0;

  constructor(capacity = INITIAL_CAPACITY) {
    this.capacity = Math.max(8, capacity);
    this.time = new Float64Array(this.capacity);
    this.open = new Float64Array(this.capacity);
    this.high = new Float64Array(this.capacity);
    this.low = new Float64Array(this.capacity);
    this.close = new Float64Array(this.capacity);
    this.volume = new Float64Array(this.capacity);
  }

  get length(): number {
    return this.count;
  }

  get revisionCount(): number {
    return this.revisions;
  }

  /** Forget every bar. Used when the chart switches symbol. */
  clear(): void {
    this.count = 0;
    this.revisions = 0;
  }

  /**
   * A copy of every column, for the indicator engine.
   *
   * The copies are deliberate: a calculation may never write into the bars
   * the renderer is drawing, and an indicator is allowed to fail without
   * corrupting the chart.
   */
  columns(): {
    time: Float64Array; open: Float64Array; high: Float64Array;
    low: Float64Array; close: Float64Array; volume: Float64Array;
  } {
    return {
      time: this.time.slice(0, this.count),
      open: this.open.slice(0, this.count),
      high: this.high.slice(0, this.count),
      low: this.low.slice(0, this.count),
      close: this.close.slice(0, this.count),
      volume: this.volume.slice(0, this.count),
    };
  }

  /** The bar at an index, or undefined outside the series. */
  at(index: number): BarRow | undefined {
    if (!Number.isInteger(index) || index < 0 || index >= this.count) {
      return undefined;
    }
    return {
      timeMs: this.time[index] ?? Number.NaN,
      o: this.open[index] ?? 0,
      h: this.high[index] ?? 0,
      l: this.low[index] ?? 0,
      c: this.close[index] ?? 0,
      v: this.volume[index] ?? 0,
    };
  }

  /**
   * Insert or replace one bar.
   *
   * Returns "appended" for a new minute, "revised" when an existing minute
   * changed, and "ignored" when the same values were published again (which
   * a poll naturally does, and which must not churn the renderer).
   */
  upsert(bar: Bar): "appended" | "revised" | "ignored" {
    const moment = timeMs(bar.t);
    if (!Number.isFinite(moment)) {
      return "ignored";
    }
    const last = this.count - 1;
    if (last >= 0 && (this.time[last] ?? 0) === moment) {
      return this.replace(last, moment, bar) ? "revised" : "ignored";
    }
    if (last < 0 || moment > (this.time[last] ?? 0)) {
      this.push(moment, bar);
      return "appended";
    }
    const found = this.indexOf(moment);
    if (found >= 0) {
      return this.replace(found, moment, bar) ? "revised" : "ignored";
    }
    this.insertAfter(this.indexOfBefore(moment), moment, bar);
    return "appended";
  }

  upsertMany(bars: readonly Bar[]): UpsertCounts {
    let appended = 0;
    let revised = 0;
    for (const bar of bars) {
      const outcome = this.upsert(bar);
      if (outcome === "appended") {
        appended += 1;
      } else if (outcome === "revised") {
        revised += 1;
      }
    }
    return { appended, revised };
  }

  /**
   * The shape a viewport needs: first and last bar, how many, and the step.
   *
   * Returned as a plain object so the drawing code can hand it straight to
   * the viewport maths without either module importing the other.
   */
  bounds(): { firstMs: number; lastMs: number; count: number; stepMs: number } | null {
    if (this.count === 0) {
      return null;
    }
    const firstMs = this.time[0] ?? 0;
    const lastMs = this.time[this.count - 1] ?? firstMs;
    return { firstMs, lastMs, count: this.count, stepMs: this.stepMs() };
  }

  /**
   * One bar's width: the median interval between recent bars.
   *
   * Not the last interval, and not the average, because a minute series is
   * full of holes: PSX stocks print nothing for long stretches, so a single
   * 74-minute hole between two bars would otherwise be taken for the bar
   * width and a chart would open hours wide with a handful of candles in it.
   * The median of the recent intervals reports the real interval (a minute)
   * and ignores the holes, which is exactly right: a hole is missing data,
   * not a wider bar. It reads at most 64 intervals, so it is O(1) per frame.
   */
  stepMs(): number {
    if (this.count < 2) {
      return 60_000;
    }
    const sample = Math.min(64, this.count - 1);
    const gaps: number[] = [];
    for (let offset = 0; offset < sample; offset += 1) {
      const index = this.count - 1 - offset;
      const later = this.time[index] ?? 0;
      const earlier = this.time[index - 1] ?? 0;
      const gap = later - earlier;
      if (gap > 0) {
        gaps.push(gap);
      }
    }
    if (gaps.length === 0) {
      return 60_000;
    }
    gaps.sort((left, right) => left - right);
    return gaps[Math.floor(gaps.length / 2)] ?? 60_000;
  }

  /**
   * The timestamps of the newest `count` bars.
   *
   * Used once per series to open a chart on the last N bars, which is not the
   * same question as "the last N minutes": a symbol with a long hole in its
   * session has its recent bars spread over hours, and a window sized in
   * minutes would show one candle and hide the rest.
   */
  timesOfLast(count: number): number[] {
    const take = Math.max(1, Math.min(this.count, Math.floor(count)));
    const times: number[] = [];
    for (let index = this.count - take; index < this.count; index += 1) {
      times.push(this.time[index] ?? 0);
    }
    return times;
  }

  /** How many bars a window contains, found by bisection rather than a scan. */
  countInWindow(fromMs: number, toMs: number): number {
    if (this.count === 0 || toMs < fromMs) {
      return 0;
    }
    const first = this.lowerBound(fromMs);
    const past = this.lowerBound(toMs);
    return Math.max(0, past - first);
  }

  /** The first index whose timestamp is at or after `moment`. */
  private lowerBound(moment: number): number {
    let lo = 0;
    let hi = this.count;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if ((this.time[mid] ?? 0) < moment) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo;
  }

  /** Index of the last bar at or before `moment`, or -1. */
  indexAtOrBefore(moment: number): number {
    if (this.count === 0 || moment < (this.time[0] ?? 0)) {
      return -1;
    }
    let lo = 0;
    let hi = this.count - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if ((this.time[mid] ?? 0) <= moment) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    return lo;
  }

  /** Inclusive index window covering [fromMs, toMs]. */
  window(fromMs: number, toMs: number): { from: number; to: number } {
    const from = Math.max(0, this.indexAtOrBefore(fromMs));
    let to = this.indexAtOrBefore(toMs);
    if (to < from) {
      to = Math.min(this.count - 1, from + 1);
    }
    return { from, to: Math.min(this.count - 1, to) };
  }

  priceRange(from: number, to: number): { min: number; max: number } {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (let index = Math.max(0, from); index <= to && index < this.count; index += 1) {
      const barLow = this.low[index] ?? 0;
      const barHigh = this.high[index] ?? 0;
      if (barLow < min) {
        min = barLow;
      }
      if (barHigh > max) {
        max = barHigh;
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      return { min: 0, max: 1 };
    }
    return { min, max };
  }

  maxVolume(from: number, to: number): number {
    let max = 0;
    for (let index = Math.max(0, from); index <= to && index < this.count; index += 1) {
      const value = this.volume[index] ?? 0;
      if (value > max) {
        max = value;
      }
    }
    return max;
  }

  /**
   * Fold the series into buckets of `bucketMs`, aligned to the epoch.
   *
   * Aggregation is only ever done for display: the underlying minute series
   * is untouched, so zooming back in shows every minute again.
   */
  aggregate(bucketMs: number): ColumnSeries {
    const folded = new ColumnSeries(Math.max(8, Math.ceil(this.count / 4)));
    if (bucketMs <= 0 || this.count === 0) {
      return folded;
    }
    let bucket = Number.NaN;
    let open = 0;
    let high = 0;
    let low = 0;
    let close = 0;
    let volume = 0;
    let started = false;

    const flush = () => {
      if (started) {
        folded.pushRaw(bucket, open, high, low, close, volume);
      }
    };

    for (let index = 0; index < this.count; index += 1) {
      const moment = this.time[index] ?? 0;
      const key = Math.floor(moment / bucketMs) * bucketMs;
      if (key !== bucket) {
        flush();
        bucket = key;
        open = this.open[index] ?? 0;
        high = this.high[index] ?? 0;
        low = this.low[index] ?? 0;
        close = this.close[index] ?? 0;
        volume = 0;
        started = true;
      } else {
        high = Math.max(high, this.high[index] ?? 0);
        low = Math.min(low, this.low[index] ?? 0);
        close = this.close[index] ?? 0;
      }
      volume += this.volume[index] ?? 0;
    }
    flush();
    return folded;
  }

  toArray(): Bar[] {
    const bars: Bar[] = [];
    for (let index = 0; index < this.count; index += 1) {
      bars.push({
        t: new Date(this.time[index] ?? 0).toISOString(),
        o: this.open[index] ?? 0,
        h: this.high[index] ?? 0,
        l: this.low[index] ?? 0,
        c: this.close[index] ?? 0,
        v: this.volume[index] ?? 0,
      });
    }
    return bars;
  }

  // ------------------------------------------------------------- internals
  private indexOf(moment: number): number {
    let lo = 0;
    let hi = this.count - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const value = this.time[mid] ?? 0;
      if (value === moment) {
        return mid;
      }
      if (value < moment) {
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return -1;
  }

  private indexOfBefore(moment: number): number {
    return this.indexAtOrBefore(moment);
  }

  private replace(index: number, moment: number, bar: Bar): boolean {
    const same =
      (this.open[index] ?? 0) === bar.o &&
      (this.high[index] ?? 0) === bar.h &&
      (this.low[index] ?? 0) === bar.l &&
      (this.close[index] ?? 0) === bar.c &&
      (this.volume[index] ?? 0) === bar.v;
    if (same) {
      return false;
    }
    this.time[index] = moment;
    this.open[index] = bar.o;
    this.high[index] = bar.h;
    this.low[index] = bar.l;
    this.close[index] = bar.c;
    this.volume[index] = bar.v;
    this.revisions += 1;
    return true;
  }

  private push(moment: number, bar: Bar): void {
    this.pushRaw(moment, bar.o, bar.h, bar.l, bar.c, bar.v);
  }

  private insertAfter(index: number, moment: number, bar: Bar): void {
    this.ensure(this.count + 1);
    for (let move = this.count; move > index + 1; move -= 1) {
      this.shift(move, move - 1);
    }
    this.time[index + 1] = moment;
    this.open[index + 1] = bar.o;
    this.high[index + 1] = bar.h;
    this.low[index + 1] = bar.l;
    this.close[index + 1] = bar.c;
    this.volume[index + 1] = bar.v;
    this.count += 1;
  }

  private shift(to: number, from: number): void {
    this.time[to] = this.time[from] ?? 0;
    this.open[to] = this.open[from] ?? 0;
    this.high[to] = this.high[from] ?? 0;
    this.low[to] = this.low[from] ?? 0;
    this.close[to] = this.close[from] ?? 0;
    this.volume[to] = this.volume[from] ?? 0;
  }

  private pushRaw(
    moment: number,
    open: number,
    high: number,
    low: number,
    close: number,
    volume: number,
  ): void {
    this.ensure(this.count + 1);
    this.time[this.count] = moment;
    this.open[this.count] = open;
    this.high[this.count] = high;
    this.low[this.count] = low;
    this.close[this.count] = close;
    this.volume[this.count] = volume;
    this.count += 1;
  }

  private ensure(needed: number): void {
    if (needed <= this.capacity) {
      return;
    }
    let capacity = this.capacity;
    while (capacity < needed) {
      capacity *= 2;
    }
    const grow = (source: Float64Array) => {
      const next = new Float64Array(capacity);
      next.set(source);
      return next;
    };
    this.time = grow(this.time);
    this.open = grow(this.open);
    this.high = grow(this.high);
    this.low = grow(this.low);
    this.close = grow(this.close);
    this.volume = grow(this.volume);
    this.capacity = capacity;
  }
}

/**
 * The bucket size to draw at, given the visible span and pixels.
 *
 * A candle narrower than about three pixels is a smudge, so buckets are
 * chosen to keep candles readable, then rounded up to a whole number of base
 * intervals so bucket edges line up with real minutes.
 */
export function bucketFor(
  spanMs: number,
  pixelWidth: number,
  baseMs = 60_000,
  minCandlePixels = 3,
): number {
  if (spanMs <= 0 || pixelWidth <= 0) {
    return baseMs;
  }
  const wanted = spanMs / Math.max(1, pixelWidth / minCandlePixels);
  const buckets = Math.max(1, Math.ceil(wanted / baseMs));
  return buckets * baseMs;
}

/**
 * The bucket to draw a window with, given how many bars it covers.
 *
 * Folding is decided by the bars in the window, never by its clock span. The
 * span is the wrong question for the same reason it is the wrong question for
 * the viewport: one hole in an illiquid session makes a window far wider than
 * the bars inside it, and a span-sized bucket then folded real one-minute
 * candles into two-minute ones although every candle had room on the canvas.
 *
 * `baseMs` is the series' own step, so a minute series folds in whole minutes
 * and a daily one in whole days, and nothing is ever folded below one step.
 */
export function displayBucket(
  visibleBars: number,
  baseMs: number,
  pixelWidth: number,
  minCandlePixels = 3,
): number {
  const step = Number.isFinite(baseMs) && baseMs > 0 ? baseMs : 60_000;
  return bucketFor(Math.max(1, visibleBars) * step, pixelWidth, step,
                   minCandlePixels);
}

/** Gaps that intersect a window, in the order the exchange printed them. */
export function gapsInWindow(
  gaps: readonly Gap[],
  fromMs: number,
  toMs: number,
): Gap[] {
  return gaps.filter((gap) => {
    const start = timeMs(gap.start);
    const end = timeMs(gap.end);
    return Number.isFinite(start) && Number.isFinite(end) && start <= toMs && end >= fromMs;
  });
}
