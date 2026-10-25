/**
 * The script language, beyond a single line.
 *
 * A reader pastes their own study: several statements, names they assigned
 * themselves, a plot wrapper, and a length that used to be refused at four
 * hundred characters. These pin the behaviour of that surface, and the
 * refusals that must stay refusals.
 */

import { describe, expect, it } from "vitest";

import { compileFormula, FormulaError, validateFormula } from "./expression";
import type { SeriesData } from "./types";

function dataFor(closes: readonly number[]): SeriesData {
  const length = closes.length;
  const time = new Float64Array(length);
  const open = new Float64Array(length);
  const high = new Float64Array(length);
  const low = new Float64Array(length);
  const close = new Float64Array(length);
  const volume = new Float64Array(length);
  closes.forEach((value, index) => {
    time[index] = index * 60_000;
    open[index] = value;
    high[index] = value + 1;
    low[index] = value - 1;
    close[index] = value;
    volume[index] = 100 + index;
  });
  return { length, time, open, high, low, close, volume };
}

describe("multi-statement scripts", () => {
  it("reads names assigned on earlier lines", () => {
    const run = compileFormula("fast = sma(close, 2)\nslow = sma(close, 3)\nfast - slow");
    const out = run(dataFor([1, 2, 3, 4, 5]));
    expect(out[4]).toBeCloseTo(0.5);
  });

  it("draws the last line even when it is an assignment", () => {
    const run = compileFormula("window = sma(close, 2)");
    const out = run(dataFor([2, 4, 6]));
    expect(out[2]).toBeCloseTo(5);
  });

  it("accepts plot() and hline() as the drawing wrappers a script carries", () => {
    expect(() => validateFormula("plot(ema(close, 3))")).not.toThrow();
    const run = compileFormula("hline(100) + change(close)");
    // hline is a constant, change(close) is one bar's move: 100 + (15 - 12).
    expect(run(dataFor([10, 12, 15]))[2]).toBeCloseTo(103);
  });

  it("survives a wrapped call, which is one statement not two", () => {
    expect(() => validateFormula("sma(\n  close,\n  3\n)")).not.toThrow();
  });

  it("names an unassigned identifier instead of guessing a series", () => {
    // Parsing cannot know an assignment that never happened, so the refusal
    // arrives when the script is run against the bars - which is exactly what
    // the editor does before it commits the line.
    expect(() => validateFormula("mystery + 1"))
      .toThrow(/unknown series or variable/);
  });

  it("refuses a comparison it does not have", () => {
    expect(() => compileFormula("close == 5")).toThrow(/not supported/);
  });

  it("holds a script far longer than the old 400-character ceiling", () => {
    const lines: string[] = [];
    for (let index = 1; index <= 80; index += 1) {
      lines.push(`a${index} = sma(close, ${index})`);
    }
    lines.push("a80");
    const script = lines.join("\n");
    expect(script.length).toBeGreaterThan(400);
    expect(() => validateFormula(script)).not.toThrow();
  });

  it("still refuses a script that never ends", () => {
    const script = "x = 1\n".repeat(4_000);
    expect(() => compileFormula(script)).toThrow(FormulaError);
  });
});
