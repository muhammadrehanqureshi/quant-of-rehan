/**
 * The screener's own reading of a session, detached from the table.
 *
 * The rule these pin is the honest one: a symbol with no measurement sorts
 * last in either direction, because an absence is not a small number.
 */

import { describe, expect, it } from "vitest";

import type { SymbolRow } from "../api/types";
import {
  filterScreened,
  screenerChange,
  sortScreened,
} from "./Screener";

function row(symbol: string, patch: Partial<SymbolRow> = {}): SymbolRow {
  return {
    symbol,
    source: "broker_tape",
    listed: true,
    index: false,
    bars: 12,
    first: "2026-10-23T09:32:00+05:00",
    last: "2026-10-23T10:00:00+05:00",
    close: 100,
    open: 98,
    high: 101,
    low: 97,
    volume: 5_000,
    day: "2026-10-23",
    ...patch,
  };
}

function screened(rows: readonly SymbolRow[]) {
  return rows.map((item) => {
    const measured = screenerChange(item);
    return {
      row: item,
      change: measured === null ? null : measured.change,
      percent: measured === null ? null : measured.percent,
    };
  });
}

describe("screener change", () => {
  it("measures against the session's own open", () => {
    expect(screenerChange(row("A"))).toEqual({ change: 2, percent: 2 / 98 * 100 });
  });

  it("says nothing when the open is missing rather than claiming a zero", () => {
    expect(screenerChange(row("A", { open: null }))).toBeNull();
    expect(screenerChange(row("A", { open: 0 }))).toBeNull();
  });
});

describe("screener sort", () => {
  const rows = screened([
    row("LOW", { close: 90, open: 100, volume: 100 }),
    row("HIGH", { close: 110, open: 100, volume: 900 }),
    row("NONE", { close: null, open: null, volume: null, bars: 0 }),
  ]);

  it("sorts the biggest riser first when descending", () => {
    expect(sortScreened(rows, "change", true).map((item) => item.row.symbol))
      .toEqual(["HIGH", "LOW", "NONE"]);
  });

  it("puts an unmeasured row last in both directions", () => {
    expect(sortScreened(rows, "change", false)[2]?.row.symbol).toBe("NONE");
    expect(sortScreened(rows, "volume", true)[2]?.row.symbol).toBe("NONE");
  });

  it("sorts symbols as text", () => {
    expect(sortScreened(rows, "symbol", false).map((item) => item.row.symbol))
      .toEqual(["HIGH", "LOW", "NONE"]);
  });
});

describe("screener filter", () => {
  const rows = screened([
    row("PRL"),
    row("KSE100", { index: true }),
    row("IDLE", { bars: 0 }),
  ]);

  it("matches a substring, case-insensitively", () => {
    expect(filterScreened(rows, "pr", false).map((item) => item.row.symbol))
      .toEqual(["PRL"]);
  });

  it("drops the untraded when only traded rows are wanted", () => {
    expect(filterScreened(rows, "", true).map((item) => item.row.symbol))
      .toEqual(["PRL", "KSE100"]);
  });
});
