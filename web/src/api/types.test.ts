/**
 * The validators stand between a network response and every number the
 * chart draws, so each rejection here is a chart that did not lie.
 */

import { describe, expect, it } from "vitest";

import {
  ContractViolation,
  parseBarEvent,
  parseErrorBody,
  parsePayload,
  parseSymbols,
} from "./types";

function payload(): Record<string, unknown> {
  return {
    ok: true,
    schema_version: 1,
    as_of: "2026-10-12T11:00:00+05:00",
    observed_at: "2026-10-12T10:59:30+05:00",
    symbol: "OGDC",
    resolution: "1m",
    source: {
      id: "broker_tape",
      label: "broker MKT-FEED tape",
      delay_seconds: 0,
      note: "read-only",
    },
    market: {
      phase: "OPEN",
      state: "MARKET",
      trading_day: true,
      timezone: "Asia/Karachi",
      band: { open: "09:32", close: "15:30" },
      next_event: { event: "CLOSE", at: "2026-10-12T15:30:00+05:00" },
      as_of: "2026-10-12T11:00:00+05:00",
    },
    bars: [
      {
        t: "2026-10-12T10:58:00+05:00",
        o: 100,
        h: 101,
        l: 99.5,
        c: 100.5,
        v: 1200,
      },
      {
        t: "2026-10-12T10:59:00+05:00",
        o: 100.5,
        h: 101.5,
        l: 100,
        c: 101,
        v: 900,
      },
    ],
    bar_count: 2,
    gaps: [
      {
        start: "2026-10-12T10:40:00+05:00",
        end: "2026-10-12T10:41:00+05:00",
        minutes: 2,
        reason: "no bar was printed in this minute",
      },
    ],
    notes: ["3 bar(s) held against 88 expected session minute(s)"],
    ingest: {
      polls: 4,
      last_poll_at: "2026-10-12T11:00:00+05:00",
      watched: ["OGDC"],
      subscribers: 1,
      dropped_events: 0,
      errors: {},
      interval_seconds: 15,
      resolution: "1m",
      source: {
        id: "broker_tape",
        label: "broker MKT-FEED tape",
        delay_seconds: 0,
        note: "read-only",
      },
    },
  };
}

describe("parsePayload", () => {
  it("accepts a well formed payload", () => {
    const parsed = parsePayload(payload());
    expect(parsed.symbol).toBe("OGDC");
    expect(parsed.bars.length).toBe(2);
    expect(parsed.market.trading_day).toBe(true);
    expect(parsed.ingest.watched).toEqual(["OGDC"]);
  });

  it("refuses a payload that says it failed", () => {
    const broken = { ...payload(), ok: false };
    expect(() => parsePayload(broken)).toThrow(ContractViolation);
  });

  it("refuses a payload missing a field it draws from", () => {
    const broken = payload();
    delete broken["symbol"];
    expect(() => parsePayload(broken)).toThrow(/payload\.symbol/);
  });

  it("refuses a timestamp with no offset", () => {
    const broken = payload();
    const bars = broken["bars"] as Record<string, unknown>[];
    const first = bars[0];
    if (first !== undefined) {
      first["t"] = "2026-10-12T10:58:00";
    }
    expect(() => parsePayload(broken)).toThrow(/UTC offset/);
  });

  it("refuses a bar whose high is below its close", () => {
    const broken = payload();
    const bars = broken["bars"] as Record<string, unknown>[];
    const first = bars[0];
    if (first !== undefined) {
      first["h"] = 99;
    }
    expect(() => parsePayload(broken)).toThrow(/high is below/);
  });

  it("refuses a bar count that disagrees with the bars it carries", () => {
    const broken = { ...payload(), bar_count: 5 };
    expect(() => parsePayload(broken)).toThrow(/bar_count/);
  });

  it("refuses a non finite price", () => {
    const broken = payload();
    const bars = broken["bars"] as Record<string, unknown>[];
    const first = bars[0];
    if (first !== undefined) {
      first["c"] = null;
    }
    expect(() => parsePayload(broken)).toThrow(/payload\.bars\[0\]\.c/);
  });

  it("refuses an unknown resolution", () => {
    const broken = { ...payload(), resolution: "5m" };
    expect(() => parsePayload(broken)).toThrow(/resolution/);
  });

  it("refuses an error body dressed up as a payload", () => {
    const error = { ok: false, error: { code: "BAD_LIMIT", detail: "no" } };
    expect(() => parsePayload(error)).toThrow(ContractViolation);
  });
});

describe("parseBarEvent", () => {
  it("accepts a bars event", () => {
    const event = parseBarEvent({
      event: "bars",
      symbol: "OGDC",
      resolution: "1m",
      as_of: "2026-10-12T11:00:00+05:00",
      bars: [],
    });
    expect(event.symbol).toBe("OGDC");
    expect(event.bars).toEqual([]);
  });

  it("refuses another event name", () => {
    expect(() =>
      parseBarEvent({ event: "snapshot", symbol: "OGDC" }),
    ).toThrow(/unexpected event/);
  });
});

describe("parseSymbols", () => {
  it("reads the catalogue", () => {
    expect(parseSymbols({ ok: true, symbols: [{ symbol: "OGDC" }] })).toEqual([
      "OGDC",
    ]);
  });

  it("refuses a row without a symbol", () => {
    expect(() => parseSymbols({ symbols: [{}] })).toThrow(ContractViolation);
  });
});

describe("parseErrorBody", () => {
  it("names the failure the server reported", () => {
    expect(
      parseErrorBody({ ok: false, error: { code: "TIMEOUT", detail: "no" } }),
    ).toEqual({ code: "TIMEOUT", detail: "no" });
  });

  it("refuses a body with no error object", () => {
    expect(() => parseErrorBody({ ok: false })).toThrow(ContractViolation);
  });
});
