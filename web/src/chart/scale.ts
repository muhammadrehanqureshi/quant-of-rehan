/**
 * Scales and ticks, which decide whether an axis reads like a chart or like
 * a spreadsheet dump.
 *
 * `niceTicks` picks a step from the 1, 2, 5 family so every label is a round
 * number, and it always covers the domain, so the highest candle is inside
 * the plot rather than clipped at the frame.
 */

export interface TickSet {
  readonly values: readonly number[];
  readonly step: number;
}

/** A scale from a data domain to a pixel range. */
export interface Scale {
  (value: number): number;
  readonly domain: readonly [number, number];
  readonly range: readonly [number, number];
}

export function linearScale(
  domain: readonly [number, number],
  range: readonly [number, number],
): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;
  const scale = ((value: number) => {
    if (span === 0) {
      return (r0 + r1) / 2;
    }
    return r0 + ((value - d0) / span) * (r1 - r0);
  }) as { (value: number): number } & {
    domain: readonly [number, number];
    range: readonly [number, number];
  };
  scale.domain = domain;
  scale.range = range;
  return scale as Scale;
}

/** A round step at or above `rough`, from the 1, 2, 5, 10 family. */
export function niceStep(rough: number): number {
  if (!Number.isFinite(rough) || rough <= 0) {
    return 1;
  }
  const exponent = Math.floor(Math.log10(rough));
  const magnitude = 10 ** exponent;
  const normalised = rough / magnitude;
  const factor = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return factor * magnitude;
}

export function niceTicks(
  min: number,
  max: number,
  count = 6,
): TickSet {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count < 1) {
    return { values: [], step: 1 };
  }
  if (max < min) {
    [min, max] = [max, min];
  }
  if (max === min) {
    const pad = Math.abs(max) * 0.01 || 1;
    min -= pad;
    max += pad;
  }
  const step = niceStep((max - min) / count);
  const first = Math.ceil(min / step) * step;
  const values: number[] = [];
  for (let value = first; value <= max + step / 1e6; value += step) {
    // Guard against floating point drift accumulating over many steps.
    values.push(Number((Math.round(value / step) * step).toPrecision(12)));
  }
  return { values, step };
}

/** How many decimals a price axis needs for a given step. */
export function decimalsFor(step: number): number {
  if (!Number.isFinite(step) || step <= 0) {
    return 2;
  }
  const decimals = Math.max(0, Math.ceil(-Math.log10(step)));
  return Math.min(6, decimals);
}
