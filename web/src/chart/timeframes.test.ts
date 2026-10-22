import { describe, expect, it } from "vitest";

import { RESOLUTIONS } from "../api/types";
import {
  TIMEFRAMES,
  timeframeLabel,
  timeframeMs,
  timeframeShort,
} from "./timeframes";

describe("timeframe ladder", () => {
  it("offers every rung the chart service can serve", () => {
    expect(TIMEFRAMES.map((item) => item.id)).toEqual([
      "1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h", "4h",
      "1D", "1W", "1M",
    ]);
    expect(new Set(RESOLUTIONS)).toEqual(new Set(TIMEFRAMES.map((item) => item.id)));
  });

  it("names each rung without falling back to its wire id", () => {
    for (const item of TIMEFRAMES) {
      expect(item.label).not.toBe(item.id);
      expect(item.short.length).toBeGreaterThan(0);
      expect(timeframeLabel(item.id)).toBe(item.label);
      expect(timeframeShort(item.id)).toBe(item.short);
    }
  });

  it("gives the renderer a positive nominal width for every rung", () => {
    expect(timeframeMs("1s")).toBe(1_000);
    expect(timeframeMs("10s")).toBe(10_000);
    expect(timeframeMs("1m")).toBe(60_000);
    expect(timeframeMs("5m")).toBe(300_000);
    expect(timeframeMs("10m")).toBe(600_000);
    expect(timeframeMs("15m")).toBe(900_000);
    expect(timeframeMs("30m")).toBe(1_800_000);
    expect(timeframeMs("1h")).toBe(3_600_000);
    expect(timeframeMs("4h")).toBe(14_400_000);
    expect(timeframeMs("1D")).toBe(86_400_000);
    expect(timeframeMs("1W")).toBe(604_800_000);
    expect(timeframeMs("1M")).toBe(2_592_000_000);
  });
});
