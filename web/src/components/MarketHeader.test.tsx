import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChartPayload } from "../api/types";
import type { FeedMeta } from "../hooks/useChartFeed";
import { MarketHeader } from "./MarketHeader";

const source = {
  id: "broker_tape",
  label: "broker MKT-FEED snapshots (~30s median per symbol)",
  delay_seconds: 0,
  note: "Measured per-symbol publication cadence is about 30 seconds.",
};

const payload = {
  ok: true,
  schema_version: 1,
  as_of: "2026-10-12T11:00:00+05:00",
  observed_at: "2026-10-12T10:59:30+05:00",
  symbol: "OGDC",
  resolution: "1m",
  source,
  market: {
    phase: "OPEN",
    state: "MARKET",
    trading_day: true,
    timezone: "Asia/Karachi",
    band: null,
    next_event: null,
    as_of: "2026-10-12T11:00:00+05:00",
  },
  bars: [],
  bar_count: 0,
  gaps: [],
  notes: [],
  ingest: {
    polls: 1,
    last_poll_at: "2026-10-12T11:00:00+05:00",
    watched: ["OGDC"],
    subscribers: 1,
    dropped_events: 0,
    errors: {},
    interval_seconds: 30,
    resolution: "1m",
    source,
  },
} satisfies ChartPayload;

const meta: FeedMeta = {
  symbol: "OGDC",
  resolution: "1m",
  market: payload.market,
  source,
  notes: [],
  gaps: [],
  payload,
  liveQuote: null,
  quoteStatus: "loading",
  quoteError: null,
};

describe("MarketHeader", () => {
  it("labels the broker observation timestamp rather than the poll time", () => {
    const html = renderToStaticMarkup(
      <MarketHeader
        meta={meta}
        status="live"
        error={null}
        revisions={0}
        bars={0}
      />,
    );
    expect(html).toContain("last broker observation");
    expect(html).toContain("12 Oct, 10:59");
    expect(html).toContain("30s median per symbol");
    expect(html).not.toContain("last update 11:00");
  });

  it("uses a fresh broker quote for price and the session change", () => {
    const html = renderToStaticMarkup(
      <MarketHeader
        meta={{
          ...meta,
          liveQuote: {
            symbol: "OGDC",
            price: 280.25,
            bid: 280,
            ask: 280.5,
            change: 2.25,
            change_pct: 0.81,
            volume: 1200,
            high: 281,
            low: 278,
            status: "OPEN",
            source_tick_time: "11:01:00",
            observed_at: "2026-10-12T11:01:00+05:00",
            age_seconds: 2,
            fresh: true,
            source: "eClear MKT-FEED REG",
          },
          quoteStatus: "live",
        }}
        status="live"
        error={null}
        revisions={0}
        bars={0}
        onRefreshQuote={() => undefined}
      />,
    );
    expect(html).toContain("280.25");
    expect(html).toContain("+0.81% session");
    expect(html).toContain("last broker quote");
    expect(html).toContain("quote age 2s");
    expect(html).toContain("refresh quote");
    expect(html).not.toContain("last broker observation");
  });

  it("does not claim an observation when none was supplied", () => {
    const emptyMeta = { ...meta, payload: null, source: null };
    const html = renderToStaticMarkup(
      <MarketHeader
        meta={emptyMeta}
        status="loading"
        error={null}
        revisions={0}
        bars={0}
      />,
    );
    expect(html).not.toContain("last broker observation");
  });
});
