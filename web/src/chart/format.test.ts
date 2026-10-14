/**
 * Formatting tests. The important one is the timezone: a viewer in another
 * zone must still read the exchange's clock, because a chart that shows
 * "08:02" to a reader in London while the venue opened at 09:32 Karachi
 * makes every candle sit in the wrong place for them.
 */

import { describe, expect, it } from "vitest";

import {
  formatClock,
  formatDay,
  formatMinutes,
  formatPrice,
  formatStamp,
  formatVolume,
} from "./format";

describe("Karachi time", () => {
  it("formats the exchange's clock whatever the input offset is", () => {
    // 05:30 UTC is 10:30 in Karachi.
    expect(formatClock("2026-10-12T05:30:00Z")).toBe("10:30");
    // The same instant written with its own offset reads identically.
    expect(formatClock("2026-10-12T10:30:00+05:00")).toBe("10:30");
  });

  it("names the day in Karachi, not in UTC", () => {
    // 20:00 UTC on the 11th is already the 12th in Karachi.
    expect(formatDay("2026-10-11T20:00:00Z")).toContain("12");
  });

  it("prints a readable stamp", () => {
    expect(formatStamp("2026-10-12T10:30:00+05:00")).toBe("12 Oct, 10:30");
  });

  it("returns the input when it cannot be parsed", () => {
    expect(formatClock("not a time")).toBe("not a time");
    expect(formatStamp("nonsense")).toBe("nonsense");
  });
});

describe("numbers", () => {
  it("groups prices and keeps the requested decimals", () => {
    expect(formatPrice(1234.5, 2)).toBe("1,234.50");
    expect(formatPrice(0.125, 3)).toBe("0.125");
  });

  it("says so when a price is not a number", () => {
    expect(formatPrice(Number.NaN)).toBe("-");
  });

  it("compacts volumes", () => {
    expect(formatVolume(950)).toBe("950");
    expect(formatVolume(12_500)).toBe("12.5K");
    expect(formatVolume(2_400_000)).toBe("2.40M");
  });

  it("reads out durations in minutes and hours", () => {
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(60)).toBe("1 h");
    expect(formatMinutes(130)).toBe("2 h 10 min");
  });
});
