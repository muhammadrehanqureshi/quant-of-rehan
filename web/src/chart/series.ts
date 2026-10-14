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
