/**
 * The drawings contract: what a round-trip keeps, what it drops, and what
 * a measurement says.
 */

// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  clearDrawings,
  loadDrawings,
  measureBetween,
  parseDrawings,
  saveDrawings,
  type Drawing,
} from "./drawings";

const A = { t: 1_800_000_000_000, price: 928.99 };
const B = { t: 1_800_006_000_000, price: 941.1 };
const SEGMENT: Drawing = {
  id: "d-1",
  kind: "trend",
  points: [A, B],
};
const RAY: Drawing = {
  id: "d-2",
  kind: "hray",
  points: [A, null],
};

describe("drawings", () => {
  it("keeps segment and one-anchor kinds through a JSON round-trip", () => {
    const json = JSON.stringify([SEGMENT, RAY]);
    const out = parseDrawings(JSON.parse(json));
    expect(out).toEqual([SEGMENT, RAY]);
  });

  it("drops garbage entries instead of crashing", () => {
    expect(parseDrawings([
      null,
      42,
      { id: "", kind: "trend", points: [A, B] },
      { id: "x", kind: "triangle", points: [A, B] },
      { id: "missing-points", kind: "hline" },
      { id: "bad-number", kind: "hline", points: [{ t: "x", price: 1 }] },
      { id: "two-hlines", kind: "hline", points: [A, B] },
      RAY,
    ])).toEqual([RAY]);
  });

  it("segment kinds require both anchors on load", () => {
    expect(parseDrawings([
      { id: "half", kind: "trend", points: [A, null] },
    ])).toEqual([]);
  });

  it("saves, loads and clears per chart key", () => {
    saveDrawings("ABOT|1m", [SEGMENT]);
    expect(loadDrawings("ABOT|1m")).toEqual([SEGMENT]);
    expect(loadDrawings("PRL|5m")).toEqual([]);

    clearDrawings("ABOT|1m", window.localStorage);
    expect(loadDrawings("ABOT|1m")).toEqual([]);
    expect(loadDrawings("PRL|5m")).toEqual([]);
  });

  it("measures a distance with its own percent and minutes", () => {
    const read = measureBetween(A, B);
    expect(read.delta).toBeCloseTo(12.11, 6);
    expect(read.up).toBe(true);
    expect(read.minutes).toBeCloseTo(100, 6);
  });

  it("a fall measures red, a stand measures grey", () => {
    expect(measureBetween(B, A).up).toBe(false);
    expect(measureBetween(
      A, { t: B.t, price: A.price },
    ).up).toBe(null);
  });

  it("an anchored zero price cannot divide for a percent", () => {
    expect(measureBetween(
      { t: A.t, price: 0 },
      { t: B.t, price: 10 },
    ).pct).toBe(0);
  });

  it("storage that refuses writes loses nothing else", () => {
    const refusing = {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => undefined,
    } as unknown as Storage;
    expect(() => clearDrawings("x", refusing)).not.toThrow();
    saveDrawings("quota-hits", [RAY]); // and a refusing writer keeps quiet
  });
});
