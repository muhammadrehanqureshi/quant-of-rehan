/**
 * The visible window: zoom, pan, fit and the honest bounds around them.
 *
 * A charting terminal lives or dies on this. The rule the whole module
 * follows is that the reader is in control of time, and the data is not: a new
 * bar arriving extends a fitted view by itself, but it never moves a window
 * the reader has chosen. So every function here is pure and takes the current
 * window, the series' own bounds, and returns the next one.
 *
 * Two details that make it feel like a professional tool rather than a
 * slider:
 *
 *  * zooming is anchored at the pointer, so the candle under the cursor stays
 *    under the cursor;
 *  * the window is clamped so it can never wander off the data entirely: at
 *    least a few bars of the series are always on screen, and the right edge
 *    is allowed one bar of slack so the newest candle is not glued to the
 *    frame.
 */

export interface Viewport {
  readonly fromMs: number;
  readonly toMs: number;
}

export interface SeriesBounds {
  readonly firstMs: number;
  readonly lastMs: number;
  readonly count: number;
  /** One bar's width, used for padding and for the minimum zoom. */
  readonly stepMs: number;
}

/** How much of a series a fresh chart shows, in bars. */
export const DEFAULT_VISIBLE_BARS = 240;

/** The most bars a reader can have on screen, so a full session still reads. */
export const MAX_VISIBLE_BARS = 2000;

/** The fewest: about five minutes of one-minute bars. */
export const MIN_VISIBLE_MS = 5 * 60_000;

const SLACK = 1;

export function boundsOf(timesMs: readonly number[]): SeriesBounds | null {
  if (timesMs.length === 0) {
    return null;
  }
  const first = timesMs[0] ?? 0;
  const last = timesMs[timesMs.length - 1] ?? first;
  const step = timesMs.length > 1 ? Math.max(1, (last - first) / (timesMs.length - 1)) : 60_000;
  return { firstMs: first, lastMs: last, count: timesMs.length, stepMs: step };
}

/** The window a chart opens with: the newest bars, plus one bar of slack. */
export function defaultViewport(
  bounds: SeriesBounds,
  visibleBars = DEFAULT_VISIBLE_BARS,
): Viewport {
  const span = spanForBars(bounds, visibleBars);
  return clampViewport({ fromMs: bounds.lastMs + bounds.stepMs - span, toMs: bounds.lastMs + bounds.stepMs }, bounds);
}

/**
 * The window that shows the newest `visibleBars` bars, by their own times.
 *
 * This is the opening view for a real session. Sizing the window in minutes
 * (defaultViewport) is right when the bars are contiguous, and wrong the
 * moment a symbol stops printing: an illiquid stock with a seventy minute
 * hole and one bar after it would open on that single candle and hide the
 * rest of its day. Asked by bar count, the window simply covers the bars.
 */
export function viewportOfLastBars(
  timesMs: readonly number[],
  visibleBars = DEFAULT_VISIBLE_BARS,
  stepMs?: number,
): Viewport | null {
  const bounds = boundsOf(timesMs);
  if (bounds === null) {
    return null;
  }
  // The slack is one bar, and the bar width is the series' own step when the
  // caller knows it. Averaging the slice instead would hand a holey symbol
  // minutes of padding per side, so the window a chart opens with would be
  // wider than the fit of the very bars it shows - and the first zoom out
  // would then narrow it. One step estimate, used everywhere.
  const step = stepMs !== undefined && stepMs > 0 ? stepMs : bounds.stepMs;
  const take = Math.max(1, Math.min(timesMs.length, Math.floor(visibleBars)));
  const firstMs = timesMs[timesMs.length - take] ?? bounds.firstMs;
  return clampViewport(
    { fromMs: firstMs - step, toMs: bounds.lastMs + step },
    { ...bounds, stepMs: step },
  );
}

/** The whole series, every bar, with the same slack at each end. */
export function fitViewport(bounds: SeriesBounds): Viewport {
  // Measured from the data's own extent rather than from the bar count times
  // a nominal width: a session with holes is wider than its bars suggest, and
  // "fit" has to include all of it or it is not a fit.
  return clampViewport(
    { fromMs: bounds.firstMs - bounds.stepMs, toMs: bounds.lastMs + bounds.stepMs },
    bounds,
  );
}

/** How wide a window of `bars` bars is, including the closing slack. */
export function spanForBars(bounds: SeriesBounds, bars: number): number {
  const wanted = Math.max(1, bars + SLACK);
  return Math.min(
    Math.max(MIN_VISIBLE_MS, wanted * bounds.stepMs),
    Math.max(MIN_VISIBLE_MS, (bounds.count + SLACK) * bounds.stepMs),
  );
}

/**
 * Keep a window over the data it describes.
 *
 * The span is never widened here (that is the caller's decision) but it is
 * never allowed below the minimum either, and the window slides rather than
 * jumping: panning past the end stops at the end.
 */
export function clampViewport(viewport: Viewport, bounds: SeriesBounds): Viewport {
  // The span is honoured, only the position moves: a window may be wider than
  // the bar count suggests when the session has holes, and shortening it here
  // would silently hide the bars the caller asked for. The zoom-out ceiling
  // lives in `zoomViewport`, where a reader is actually asking to zoom out.
  const span = Math.max(MIN_VISIBLE_MS, viewport.toMs - viewport.fromMs);
  // The window may start anywhere from one bar before the first bar to one
  // bar before the newest (so the newest candle sits at the right edge with
  // its slack). A window wider than the whole series cannot satisfy both, so
  // the right edge wins: the newest bars are what a reader needs to see.
  const leftMost = bounds.firstMs - bounds.stepMs;
  const rightMost = bounds.lastMs + bounds.stepMs;
  const wanted = Math.min(viewport.fromMs, rightMost - span);
  const fromMs = Math.max(wanted, Math.min(leftMost, rightMost - span));
  return { fromMs, toMs: fromMs + span };
}

/**
 * The widest window that still means something: the window that holds every
 * bar, with the same slack at each end that `fitViewport` gives it.
 *
 * Measured from the data's own extent, not from its bar count times a nominal
 * width, so that this ceiling and `fitViewport` are the same window: on a
 * series with a hole the count-based span is *narrower* than the data, and
 * zooming out would then have zoomed in, dropping bars off the left edge while
 * a reader asked for more of them.
 */
export function widestSpan(bounds: SeriesBounds): number {
  return Math.max(MIN_VISIBLE_MS,
                  bounds.lastMs - bounds.firstMs + 2 * bounds.stepMs);
}

/**
 * Zoom by a factor, holding the bar under `anchorRatio` still.
 *
 * `anchorRatio` is where the pointer is across the plot, 0 at the left edge
 * and 1 at the right. A factor below 1 zooms in, above 1 zooms out.
 */
export function zoomViewport(
  viewport: Viewport,
  bounds: SeriesBounds,
  factor: number,
  anchorRatio: number,
): Viewport {
  const span = viewport.toMs - viewport.fromMs;
  const next = Math.max(MIN_VISIBLE_MS,
                        Math.min(widestSpan(bounds), span * factor));
  if (next === span) {
    return viewport;
  }
  const anchor = viewport.fromMs + span * Math.min(1, Math.max(0, anchorRatio));
  const ratio = Math.min(1, Math.max(0, anchorRatio));
  const fromMs = anchor - next * ratio;
  return clampViewport({ fromMs, toMs: fromMs + next }, bounds);
}

/** Move the window by a fraction of itself; positive moves forward in time. */
export function panViewport(
  viewport: Viewport,
  bounds: SeriesBounds,
  fraction: number,
): Viewport {
  const span = viewport.toMs - viewport.fromMs;
  const shift = span * fraction;
  return clampViewport(
    { fromMs: viewport.fromMs + shift, toMs: viewport.toMs + shift },
    bounds,
  );
}

/** Is the right edge at (or past) the newest bar? */
export function isAtNewest(viewport: Viewport, bounds: SeriesBounds): boolean {
  return viewport.toMs >= bounds.lastMs + bounds.stepMs - 1;
}

/** The readout sentence for the range indicator. */
export function barsInViewportLabel(shown: number, total: number): string {
  if (total === 0) {
    return "no bars";
  }
  return `showing ${shown} of ${total} bar${total === 1 ? "" : "s"}`;
}

/** Bars inside a window, for the "showing N of M" readout. */
export function barsInViewport(
  timesMs: readonly number[],
  viewport: Viewport,
): number {
  let count = 0;
  for (const moment of timesMs) {
    if (moment >= viewport.fromMs && moment < viewport.toMs) {
      count += 1;
    }
  }
  return count;
}

/**
 * The window to keep when the series changed under an existing view.
 *
 * Called after every poll. `following` is the reader's own intent, tracked by
 * the caller (it is true until they pan or zoom away from the newest bar):
 * when it is true the window slides forward with the data, and when it is
 * false the window is left exactly where the reader put it. Deriving intent
 * from the old window instead would be wrong, because a window that was at
 * the newest bar before a poll is no longer at it afterwards - that is the
 * difference between following the market and being dragged by it.
 */
export function followViewport(
  viewport: Viewport | null,
  bounds: SeriesBounds | null,
  following = true,
  visibleBars = DEFAULT_VISIBLE_BARS,
): Viewport | null {
  if (bounds === null) {
    return viewport;
  }
  if (viewport === null) {
    return defaultViewport(bounds, visibleBars);
  }
  const span = viewport.toMs - viewport.fromMs;
  if (following) {
    return clampViewport(
      { fromMs: bounds.lastMs + bounds.stepMs - span,
        toMs: bounds.lastMs + bounds.stepMs },
      bounds,
    );
  }
  return clampViewport(viewport, bounds);
}
