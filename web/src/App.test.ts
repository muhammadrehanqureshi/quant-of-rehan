/**
 * Where the app opens.
 *
 * A first visit has no last symbol, so the tape decides: the session's most
 * traded scrip. An index answers only when nothing traded, because a breadth
 * gauge is not a chart anyone opens the terminal to read.
 */

import { describe, expect, it } from "vitest";

import { openingSymbol } from "./App";
import type { SymbolRow } from "./api/types";

function row(symbol: string, patch: Partial<SymbolRow> = {}): SymbolRow {
  return {
    symbol,
    source: "broker_tape",
    listed: true,
    index: false,
    bars: 40,
    first: "2026-10-23T09:32:00+05:00",
    last: "2026-10-23T11:59:00+05:00",
    close: 100,
    open: 98,
    high: 101,
    low: 97,
    volume: 1_000,
    day: "2026-10-23",
    ...patch,
  };
}

describe("the opening chart", () => {
  it("is the session's most traded scrip, not the first row", () => {
    const chosen = openingSymbol([
      row("KSE100", { index: true, volume: 9_000_000 }),
      row("QUIET", { volume: 200 }),
      row("BUSY", { volume: 8_000_000 }),
    ]);
    expect(chosen?.symbol).toBe("BUSY");
  });

  it("skips an index even when the index traded more", () => {
    const chosen = openingSymbol([
      row("KMIALLSHR", { index: true, volume: 5_000_000 }),
      row("PRL", { volume: 300_000 }),
    ]);
    expect(chosen?.symbol).toBe("PRL");
  });

  it("answers with an index when nothing traded", () => {
    const chosen = openingSymbol([
      row("KSE100", { index: true, bars: 0, volume: null }),
      row("IDLE", { bars: 0 }),
    ]);
    expect(chosen?.symbol).toBe("KSE100");
  });

  it("says nothing when the catalogue is empty", () => {
    expect(openingSymbol([])).toBeUndefined();
  });
});
