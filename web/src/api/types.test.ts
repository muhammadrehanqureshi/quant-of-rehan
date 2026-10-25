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
  parseSessions,
  parseSymbolRows,
  parseSymbols,
} from "./types";

function payload(): Record<string, unknown> {
  return {
    ok: true,
    schema_version: 1,
    as_of: "2026-10-12T11:00:00+05:00",
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
    const broken = { ...payload(), resolution: "7m" };
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

describe("the session block (schema v2)", () => {
  const session = {
    day: "2026-10-14",
    current: false,
    archived: true,
    source: "capture_20261014.ndjson",
    capture: {
      name: "capture_20261014.ndjson",
      bytes: 13101212,
      mtime_ns: 1_791_960_305_449_193_600,
      sha256: "a".repeat(64),
    },
    built_at: "2026-10-16T14:22:54+05:00",
    note: "this is the archived 2026-10-14 session",
    volume_available: true,
  };

  it("reads which session a series belongs to", () => {
    const parsed = parsePayload({
      ...payload(),
      schema_version: 2,
      session,
    });
    expect(parsed.session.day).toBe("2026-10-14");
    expect(parsed.session.archived).toBe(true);
    expect(parsed.session.current).toBe(false);
    expect(parsed.session.capture?.name).toBe("capture_20261014.ndjson");
    expect(parsed.session.volume_available).toBe(true);
  });

  it("tolerates a pre-v2 answer without inventing a session", () => {
    const raw = payload();
    delete (raw as Record<string, unknown>)["session"];
    const parsed = parsePayload(raw);
    expect(parsed.session.day).toBe("");
    expect(parsed.session.capture).toBeNull();
    expect(parsed.session.volume_available).toBe(false);
  });

  it("treats a missing volume answer as not reported", () => {
    const bare = { ...session } as Record<string, unknown>;
    delete bare["volume_available"];
    const parsed = parsePayload({ ...payload(), session: bare });
    expect(parsed.session.volume_available).toBe(false);
  });
});

describe("parseSymbolRows", () => {
  it("keeps the per-session facts, and a missing fact stays null", () => {
    const rows = parseSymbolRows({
      ok: true,
      day: "2026-10-14",
      symbols: [
        { symbol: "OGDC", source: "broker_tape", listed: true, bars: 128,
          first: "2026-10-14T10:30:00+05:00", last: "2026-10-14T12:34:00+05:00",
          close: 296.45, day: "2026-10-14" },
        { symbol: "PPL", source: "broker_tape", listed: true, bars: 0,
          first: null, last: null, close: null, day: "2026-10-14" },
      ],
    });
    expect(rows[0]?.close).toBe(296.45);
    expect(rows[0]?.bars).toBe(128);
    expect(rows[1]?.close).toBeNull();
    expect(rows[1]?.bars).toBe(0);
    expect(rows[1]?.last).toBeNull();
  });

  it("reads a plain catalogue where the facts were never asked for", () => {
    const rows = parseSymbolRows({ symbols: [{ symbol: "OGDC" }] });
    expect(rows[0]?.listed).toBe(true);
    expect(rows[0]?.bars).toBeNull();
  });
});

describe("parseSessions", () => {
  it("reads the days a service can draw, with their identity", () => {
    const report = parseSessions({
      ok: true,
      today: "2026-10-16",
      timezone: "Asia/Karachi",
      sessions: [
        {
          day: "2026-10-16",
          current: true,
          archived: true,
          capture: { name: "capture_20261016.ndjson", bytes: 73550171,
                     mtime_ns: 1, sha256: "b".repeat(64) },
          archive: {
            day: "2026-10-16", symbols: 290, bars: 36595,
            priced_bars: 36037, carried_bars: 558, volume_available: true,
            capture: null, built_at: "2026-10-16T14:23:08+05:00", builds: 1,
            first_observation: "2026-10-16T10:05:41+05:00", notes: ["a note"],
          },
          sources: ["C:/somewhere/capture_20261016.ndjson"],
        },
        {
          day: "2026-10-14",
          current: false,
          archived: false,
          capture: null,
          archive: null,
          sources: [],
        },
      ],
    });
    expect(report.today).toBe("2026-10-16");
    expect(report.timezone).toBe("Asia/Karachi");
    expect(report.sessions.map((row) => row.day))
      .toEqual(["2026-10-16", "2026-10-14"]);
    expect(report.sessions[0]?.archive?.bars).toBe(36595);
    expect(report.sessions[1]?.archive).toBeNull();
    expect(report.sessions[1]?.sources).toEqual([]);
  });

  it("refuses an answer with no today", () => {
    expect(() => parseSessions({ sessions: [] })).toThrow(ContractViolation);
  });
});
