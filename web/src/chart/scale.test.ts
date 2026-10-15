import { describe, expect, it } from "vitest";

import { decimalsFor, linearScale, niceStep, niceTicks } from "./scale";

describe("niceStep", () => {
  it("rounds up to the 1, 2, 5 family", () => {
    expect(niceStep(0.9)).toBe(1);
    expect(niceStep(1.4)).toBe(2);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(7)).toBe(10);
    expect(niceStep(23)).toBe(50);
  });

  it("is defensive about a nonsense step", () => {
    expect(niceStep(0)).toBe(1);
    expect(niceStep(-5)).toBe(1);
  });
});

describe("niceTicks", () => {
  it("covers the domain with round values", () => {
    const ticks = niceTicks(97, 104, 6);
    expect(ticks.step).toBe(2);
    expect(ticks.values).toContain(98);
    expect(ticks.values).toContain(104);
    const first = ticks.values[0] ?? Number.NaN;
    const last = ticks.values[ticks.values.length - 1] ?? Number.NaN;
    expect(first).toBeGreaterThanOrEqual(97);
    expect(last).toBeLessThanOrEqual(104);
  });

  it("widens a flat domain so a chart is not a single line", () => {
    const ticks = niceTicks(100, 100, 4);
    expect(ticks.values.length).toBeGreaterThan(0);
    expect(ticks.step).toBeGreaterThan(0);
  });

  it("handles min and max given the wrong way round", () => {
    expect(niceTicks(110, 100, 4).values[0]).toBeLessThanOrEqual(110);
  });

  it("says nothing for an unusable request", () => {
    expect(niceTicks(Number.NaN, 5, 4).values).toEqual([]);
    expect(niceTicks(0, 5, 0).values).toEqual([]);
  });
});

describe("linearScale", () => {
  it("maps the domain onto the range", () => {
    const scale = linearScale([0, 10], [100, 200]);
    expect(scale(0)).toBe(100);
    expect(scale(10)).toBe(200);
    expect(scale(5)).toBe(150);
  });

  it("inverts for a chart's y axis", () => {
    const scale = linearScale([10, 20], [200, 100]);
    expect(scale(10)).toBe(200);
    expect(scale(20)).toBe(100);
  });

  it("places a zero span in the middle instead of dividing by zero", () => {
    const scale = linearScale([5, 5], [0, 100]);
    expect(scale(5)).toBe(50);
  });
});

describe("decimalsFor", () => {
  it("asks for the decimals a step needs", () => {
    expect(decimalsFor(1)).toBe(0);
    expect(decimalsFor(0.5)).toBe(1);
    expect(decimalsFor(0.05)).toBe(2);
    expect(decimalsFor(0)).toBe(2);
  });
});
