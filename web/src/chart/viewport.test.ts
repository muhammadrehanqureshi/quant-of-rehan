/**
 * The viewport maths, tested as maths.
 *
 * Every assertion here is about the promise made to the reader: the window
 * follows the newest bar while they are watching it, and it stays exactly
 * where they left it the moment they scroll back. A chart that quietly slides
 * while someone is reading an old candle is the failure this suite exists to
 * prevent.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_VISIBLE_BARS,
  MAX_VISIBLE_BARS,
  MIN_VISIBLE_MS,
  type SeriesBounds,
  barsInViewport,
  boundsOf,
  clampViewport,
  defaultViewport,
  fitViewport,
  followViewport,
  isAtNewest,
  panViewport,
  spanForBars,
  viewportOfLastBars,
  widestSpan,
  zoomViewport,
} from "./viewport";

const MINUTE = 60_000;

/**
 * A session that stopped printing: 37 bars spread over 120 minutes by an 84
 * minute hole, whose own bar width is still a minute. Built by hand rather
 * than from `boundsOf`, because the whole point of it is that the bar count
 * and the clock extent disagree.
 */
const HOLEY: SeriesBounds = {
  firstMs: 1_700_000_000_000,
  lastMs: 1_700_000_000_000 + 120 * MINUTE,
  count: 37,
  stepMs: MINUTE,
};

/** A session of `count` one-minute bars, oldest first. */
function session(count: number, startMs = 1_700_000_000_000) {
  const times = Array.from({ length: count }, (_, index) => startMs + index * MINUTE);
  return { times, bounds: boundsOf(times) };
}

describe("boundsOf", () => {
  it("reports nothing for an empty series", () => {
    expect(boundsOf([])).toBeNull();
  });

  it("takes the step from the series itself", () => {
    const { bounds } = session(10);
    expect(bounds?.firstMs).toBe(1_700_000_000_000);
    expect(bounds?.lastMs).toBe(1_700_000_000_000 + 9 * MINUTE);
    expect(bounds?.stepMs).toBe(MINUTE);
    expect(bounds?.count).toBe(10);
  });

  it("assumes a minute for a single bar", () => {
    expect(boundsOf([1_700_000_000_000])?.stepMs).toBe(MINUTE);
  });
});

describe("defaultViewport", () => {
  it("opens on the newest bars with one bar of slack", () => {
    const { bounds } = session(1000);
    const view = defaultViewport(bounds!);
    expect(bounds!.lastMs).toBeGreaterThanOrEqual(view.fromMs);
    expect(view.toMs).toBe(bounds!.lastMs + MINUTE);
    const shown = (view.toMs - view.fromMs) / MINUTE;
    expect(shown).toBe(DEFAULT_VISIBLE_BARS + 1);
  });

  it("shows the whole series when it is shorter than a screen", () => {
    const { bounds } = session(40);
    const view = defaultViewport(bounds!);
    expect(view.toMs - view.fromMs).toBe(spanForBars(bounds!, 40));
    expect(view.fromMs).toBeLessThan(bounds!.firstMs);
  });

  it("never opens wider than the data allows", () => {
    const { bounds } = session(30);
    const view = defaultViewport(bounds!, MAX_VISIBLE_BARS);
    expect(view.toMs - view.fromMs).toBeLessThanOrEqual(spanForBars(bounds!, 30));
  });
});

describe("zoomViewport", () => {
  it("keeps the anchored bar under the pointer", () => {
    const { bounds } = session(600);
    const view = defaultViewport(bounds!);
    const anchorRatio = 0.25;
    const anchoredMs = view.fromMs + (view.toMs - view.fromMs) * anchorRatio;
    const zoomed = zoomViewport(view, bounds!, 0.5, anchorRatio);
    const afterMs = zoomed.fromMs + (zoomed.toMs - zoomed.fromMs) * anchorRatio;
    expect(Math.abs(afterMs - anchoredMs)).toBeLessThan(1);
    expect(zoomed.toMs - zoomed.fromMs).toBeCloseTo((view.toMs - view.fromMs) / 2, 6);
  });

  it("stops zooming out at the whole series", () => {
    const { bounds } = session(120);
    let view = defaultViewport(bounds!, 60);
    for (let step = 0; step < 10; step += 1) {
      view = zoomViewport(view, bounds!, 2, 0.5);
    }
    expect(view.toMs - view.fromMs).toBe(spanForBars(bounds!, 120));
  });

  it("stops zooming in at the minimum window", () => {
    const { bounds } = session(600);
    let view = defaultViewport(bounds!);
    for (let step = 0; step < 20; step += 1) {
      view = zoomViewport(view, bounds!, 0.5, 0.5);
    }
    expect(view.toMs - view.fromMs).toBe(MIN_VISIBLE_MS);
  });

  it("is a no-op when the factor cannot change anything", () => {
    const { bounds } = session(30);
    const view = fitViewport(bounds!);
    expect(zoomViewport(view, bounds!, 1, 0.5)).toEqual(view);
  });

  it("stops zooming out at the data's own extent, hole and all", () => {
    const fitted = fitViewport(HOLEY);
    expect(fitted.toMs - fitted.fromMs).toBe(122 * MINUTE);
    let view = fitted;
    for (let step = 0; step < 5; step += 1) {
      view = zoomViewport(view, HOLEY, 1.5, 0.5);
    }
    // Already showing every bar, so zooming out changes nothing. Counting
    // bars times a minute would have called 38 minutes the widest window,
    // which is narrower than the data: zooming out would have zoomed in.
    expect(view).toEqual(fitted);
  });

  it("never narrows a window when a reader asks for more", () => {
    const view = { fromMs: HOLEY.lastMs + MINUTE - 40 * MINUTE,
                   toMs: HOLEY.lastMs + MINUTE };
    const out = zoomViewport(view, HOLEY, 1.5, 0.5);
    expect(out.toMs - out.fromMs).toBeGreaterThanOrEqual(view.toMs - view.fromMs);
    expect(out.toMs - out.fromMs).toBeCloseTo(
      Math.min(60 * MINUTE, widestSpan(HOLEY)), 6);
  });
});

describe("widestSpan", () => {
  it("is the same window fit gives, so the ceiling and the fit agree", () => {
    const fitted = fitViewport(HOLEY);
    expect(widestSpan(HOLEY)).toBe(fitted.toMs - fitted.fromMs);
    expect(widestSpan(HOLEY)).toBeGreaterThan(HOLEY.count * HOLEY.stepMs);
  });

  it("is every bar plus its slack on a series with no holes", () => {
    const { bounds } = session(50);
    expect(widestSpan(bounds!)).toBe(51 * MINUTE);
    expect(widestSpan(bounds!)).toBe(spanForBars(bounds!, 50));
  });

  it("never goes below the minimum window", () => {
    expect(widestSpan({ firstMs: 0, lastMs: 0, count: 1, stepMs: 60_000 }))
      .toBe(MIN_VISIBLE_MS);
  });
});

describe("panViewport", () => {
  it("moves by a fraction of the window", () => {
    const { bounds } = session(600);
    const view = defaultViewport(bounds!, 100);
    const moved = panViewport(view, bounds!, -0.5);
    const shift = view.toMs - view.fromMs;
    expect(moved.fromMs).toBeCloseTo(view.fromMs - shift * 0.5, 6);
  });

  it("stops at the newest bar rather than running past it", () => {
    const { bounds } = session(600);
    const view = defaultViewport(bounds!, 100);
    const pushed = panViewport(view, bounds!, 1);
    expect(pushed.toMs).toBe(bounds!.lastMs + MINUTE);
    expect(isAtNewest(pushed, bounds!)).toBe(true);
  });

  it("stops at the oldest bar", () => {
    const { bounds } = session(600);
    const view = defaultViewport(bounds!, 100);
    const pulled = panViewport(view, bounds!, -100);
    expect(pulled.fromMs).toBe(bounds!.firstMs - MINUTE);
  });
});

describe("fitViewport", () => {
  it("shows every bar", () => {
    const { bounds } = session(345);
    const view = fitViewport(bounds!);
    expect(barsInViewport(Array.from({ length: 345 }, (_, i) => bounds!.firstMs + i * MINUTE), view))
      .toBe(345);
  });
});

describe("followViewport", () => {
  it("opens a default window when there is none", () => {
    const { bounds } = session(500);
    expect(followViewport(null, bounds!)).toEqual(defaultViewport(bounds!));
  });

  it("follows the newest bar while the reader is following", () => {
    const { bounds } = session(500);
    const view = defaultViewport(bounds!, 60);
    const grown = { ...bounds!, lastMs: bounds!.lastMs + 5 * MINUTE, count: 505 };
    const followed = followViewport(view, grown, true, 60);
    expect(followed?.toMs).toBe(grown.lastMs + MINUTE);
    // The span the reader chose is kept: following is not a re-fit.
    expect(followed!.toMs - followed!.fromMs).toBe(view.toMs - view.fromMs);
  });

  it("never moves a window the reader has scrolled back", () => {
    const { bounds } = session(500);
    const scrolled = clampViewport(
      { fromMs: bounds!.firstMs, toMs: bounds!.firstMs + 60 * MINUTE },
      bounds!,
    );
    expect(isAtNewest(scrolled, bounds!)).toBe(false);
    const grown = { ...bounds!, lastMs: bounds!.lastMs + 5 * MINUTE, count: 505 };
    expect(followViewport(scrolled, grown, false, 60)).toEqual(scrolled);
  });

  it("keeps the old window when there is no data at all", () => {
    const { bounds } = session(10);
    const view = defaultViewport(bounds!);
    expect(followViewport(view, null)).toEqual(view);
  });
});

describe("barsInViewport", () => {
  it("counts the bars a window covers", () => {
    const { times } = session(100);
    const view = { fromMs: times[10] ?? 0, toMs: times[20] ?? 0 };
    expect(barsInViewport(times, view)).toBe(10);
  });

  it("counts nothing for an empty series", () => {
    expect(barsInViewport([], { fromMs: 0, toMs: 1000 })).toBe(0);
  });
});

describe("viewportOfLastBars", () => {
  it("covers the newest bars by their own times", () => {
    const { times } = session(500);
    const view = viewportOfLastBars(times, 60);
    expect(view).not.toBeNull();
    // Sixty bars asked for, and the one bar of slack this module gives every
    // window, which is the same bargain defaultViewport makes: the oldest bar
    // it covers sits on the left edge rather than glued to it.
    expect(barsInViewport(times, view!)).toBe(61);
    expect(view!.fromMs).toBe(times[times.length - 61] ?? 0);
    expect(view!.toMs).toBe((times[times.length - 1] ?? 0) + MINUTE);
  });

  it("covers the requested bars even when they span a long time", () => {
    // The same shape as the hole test below, but counted: forty minutes, a
    // seventy-four minute hole, then the newest bar. Ten bars back from the
    // end is inside the first block, so the window has to be an hour wide to
    // hold them: asking in minutes would have failed this.
    const start = 1_700_000_000_000;
    const times = [
      ...Array.from({ length: 40 }, (_, index) => start + index * MINUTE),
      start + (40 + 74) * MINUTE,
    ];
    const view = viewportOfLastBars(times, 10);
    expect(view).not.toBeNull();
    // The step this series reports is its own average spacing: 114 minutes of
    // data across forty gaps, so 171 seconds. Ten bars back from the newest
    // starts at times[31], the window gives that one step of slack to the
    // left, and a step that wide takes in two more one-minute bars.
    const step = boundsOf(times)?.stepMs ?? 0;
    expect(view!.fromMs).toBe((times[31] ?? 0) - step);
    expect(view!.fromMs).toBeGreaterThan(times[28] ?? 0);
    expect(barsInViewport(times, view!)).toBe(12);
    // Which is the whole point: ten bars of a holey session need far more
    // than ten minutes of window, and a minute-sized one showed a candle.
    expect(view!.toMs - view!.fromMs).toBeGreaterThan(60 * MINUTE);
  });

  it("keeps every recent bar when the session has a long hole", () => {
    // The real shape that broke the first version: 40 minutes, a 74 minute
    // hole, one more bar. Sizing the window in minutes showed one candle.
    const start = 1_700_000_000_000;
    const times = [
      ...Array.from({ length: 40 }, (_, index) => start + index * MINUTE),
      start + (40 + 74) * MINUTE,
    ];
    const view = viewportOfLastBars(times, 240);
    expect(view).not.toBeNull();
    expect(barsInViewport(times, view!)).toBe(41);
  });

  it("takes its slack from the step it is given, not from the slice", () => {
    // The holey shape again: the average interval across the slice is 2.85
    // minutes, but the series' own step is one minute, and the padding has to
    // be the bar width. Rescaling from the average made the opening window
    // wider than the fit of the bars it shows.
    const start = 1_700_000_000_000;
    const times = [
      ...Array.from({ length: 40 }, (_, index) => start + index * MINUTE),
      start + (40 + 74) * MINUTE,
    ];
    const wide = viewportOfLastBars(times, 240);
    const exact = viewportOfLastBars(times, 240, MINUTE);
    expect(wide!.toMs - wide!.fromMs).toBeGreaterThan(
      exact!.toMs - exact!.fromMs);
    expect(exact!.fromMs).toBe((times[0] ?? 0) - MINUTE);
    expect(exact!.toMs).toBe((times[times.length - 1] ?? 0) + MINUTE);
    expect(barsInViewport(times, exact!)).toBe(times.length);
  });

  it("returns nothing for an empty series", () => {
    expect(viewportOfLastBars([], 60)).toBeNull();
    expect(viewportOfLastBars([], 60, MINUTE)).toBeNull();
  });

  it("opens on the whole series when it is shorter than a screen", () => {
    const { times } = session(12);
    const view = viewportOfLastBars(times, 240);
    expect(barsInViewport(times, view!)).toBe(12);
  });
});
