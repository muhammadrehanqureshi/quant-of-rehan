/**
 * Vector helpers for indicators.
 *
 * Every function returns a Float64Array of the same length as its input, with
 * NaN where the value is not yet defined (the first `period - 1` bars of a
 * moving average, for example). NaN is the honest absence: the renderer skips
 * those points rather than drawing a line from a made-up zero.
 */

export function filled(length: number, value = Number.NaN): Float64Array {
  const out = new Float64Array(length);
  // NaN is the sentinel for "not defined yet", so it must actually be
  // written: a fresh Float64Array holds zeros, and a zero would draw a line
  // from the origin for a moving average that has not warmed up.
  out.fill(value);
  return out;
}

export function sma(values: Float64Array, period: number): Float64Array {
  const out = filled(values.length);
  const window = Math.max(1, Math.floor(period));
  if (window > values.length) {
    return out;
  }
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index] ?? 0;
    if (index >= window) {
      sum -= values[index - window] ?? 0;
    }
    if (index >= window - 1) {
      out[index] = sum / window;
    }
  }
  return out;
}

export function ema(values: Float64Array, period: number): Float64Array {
  const out = filled(values.length);
  const window = Math.max(1, Math.floor(period));
  if (window > values.length) {
    return out;
  }
  const alpha = 2 / (window + 1);
  let seed = 0;
  for (let index = 0; index < window; index += 1) {
    seed += values[index] ?? 0;
  }
  let previous = seed / window;
  out[window - 1] = previous;
  for (let index = window; index < values.length; index += 1) {
    previous = (values[index] ?? 0) * alpha + previous * (1 - alpha);
    out[index] = previous;
  }
  return out;
}

/** Wilder's smoothing, the original RSI definition. */
export function rsi(values: Float64Array, period = 14): Float64Array {
  const out = filled(values.length);
  const window = Math.max(2, Math.floor(period));
  if (values.length <= window) {
    return out;
  }
  let gain = 0;
  let loss = 0;
  for (let index = 1; index <= window; index += 1) {
    const change = (values[index] ?? 0) - (values[index - 1] ?? 0);
    if (change >= 0) {
      gain += change;
    } else {
      loss -= change;
    }
  }
  let averageGain = gain / window;
  let averageLoss = loss / window;
  out[window] = averageLoss === 0 ? 100 : 100 - 100 / (1 + averageGain / averageLoss);
  for (let index = window + 1; index < values.length; index += 1) {
    const change = (values[index] ?? 0) - (values[index - 1] ?? 0);
    averageGain = (averageGain * (window - 1) + Math.max(0, change)) / window;
    averageLoss = (averageLoss * (window - 1) + Math.max(0, -change)) / window;
    out[index] = averageLoss === 0
      ? 100
      : 100 - 100 / (1 + averageGain / averageLoss);
  }
  return out;
}

export function standardDeviation(values: Float64Array, period: number): Float64Array {
  const out = filled(values.length);
  const window = Math.max(2, Math.floor(period));
  for (let index = window - 1; index < values.length; index += 1) {
    let sum = 0;
    let sumSquares = 0;
    for (let at = index - window + 1; at <= index; at += 1) {
      const value = values[at] ?? 0;
      sum += value;
      sumSquares += value * value;
    }
    const mean = sum / window;
    out[index] = Math.sqrt(Math.max(0, sumSquares / window - mean * mean));
  }
  return out;
}

export function trueRange(
  high: Float64Array,
  low: Float64Array,
  close: Float64Array,
): Float64Array {
  const out = filled(high.length);
  for (let index = 0; index < high.length; index += 1) {
    const previous = index > 0 ? (close[index - 1] ?? 0) : (close[index] ?? 0);
    const highValue = high[index] ?? 0;
    const lowValue = low[index] ?? 0;
    out[index] = Math.max(
      highValue - lowValue,
      Math.abs(highValue - previous),
      Math.abs(lowValue - previous),
    );
  }
  return out;
}

export function atr(
  high: Float64Array,
  low: Float64Array,
  close: Float64Array,
  period = 14,
): Float64Array {
  return ema(trueRange(high, low, close), period);
}

export function highest(values: Float64Array, period: number): Float64Array {
  const out = filled(values.length);
  const window = Math.max(1, Math.floor(period));
  for (let index = window - 1; index < values.length; index += 1) {
    let best = Number.NEGATIVE_INFINITY;
    for (let at = index - window + 1; at <= index; at += 1) {
      best = Math.max(best, values[at] ?? Number.NEGATIVE_INFINITY);
    }
    out[index] = best;
  }
  return out;
}

export function lowest(values: Float64Array, period: number): Float64Array {
  const out = filled(values.length);
  const window = Math.max(1, Math.floor(period));
  for (let index = window - 1; index < values.length; index += 1) {
    let best = Number.POSITIVE_INFINITY;
    for (let at = index - window + 1; at <= index; at += 1) {
      best = Math.min(best, values[at] ?? Number.POSITIVE_INFINITY);
    }
    out[index] = best;
  }
  return out;
}

export function rateOfChange(values: Float64Array, period = 10): Float64Array {
  const out = filled(values.length);
  const window = Math.max(1, Math.floor(period));
  for (let index = window; index < values.length; index += 1) {
    const previous = values[index - window] ?? Number.NaN;
    if (previous !== 0 && Number.isFinite(previous)) {
      out[index] = ((values[index] ?? 0) / previous - 1) * 100;
    }
  }
  return out;
}

export function obv(close: Float64Array, volume: Float64Array): Float64Array {
  const out = filled(close.length);
  let running = 0;
  for (let index = 0; index < close.length; index += 1) {
    if (index > 0) {
      const move = (close[index] ?? 0) - (close[index - 1] ?? 0);
      running += move > 0 ? (volume[index] ?? 0)
        : move < 0 ? -(volume[index] ?? 0) : 0;
    }
    out[index] = running;
  }
  return out;
}

/** Session-anchored VWAP. A new Karachi date resets the accumulator. */
export function vwap(
  time: Float64Array,
  high: Float64Array,
  low: Float64Array,
  close: Float64Array,
  volume: Float64Array,
): Float64Array {
  const out = filled(close.length);
  let priceVolume = 0;
  let totalVolume = 0;
  let currentDay = "";
  for (let index = 0; index < close.length; index += 1) {
    const moment = new Date(time[index] ?? 0);
    const day = Number.isNaN(moment.getTime())
      ? ""
      : moment.toLocaleDateString("en-CA", { timeZone: "Asia/Karachi" });
    if (day !== currentDay) {
      currentDay = day;
      priceVolume = 0;
      totalVolume = 0;
    }
    const typical = ((high[index] ?? 0) + (low[index] ?? 0) +
      (close[index] ?? 0)) / 3;
    const traded = volume[index] ?? 0;
    priceVolume += typical * traded;
    totalVolume += traded;
    out[index] = totalVolume > 0 ? priceVolume / totalVolume : typical;
  }
  return out;
}

/** Element-wise comparison helper, used by the formula evaluator. */
export function elementwise(
  left: number | Float64Array,
  right: number | Float64Array,
  length: number,
  op: (a: number, b: number, index: number) => number,
): Float64Array {
  const out = new Float64Array(length);
  for (let index = 0; index < length; index += 1) {
    const a = typeof left === "number" ? left : (left[index] ?? Number.NaN);
    const b = typeof right === "number" ? right : (right[index] ?? Number.NaN);
    out[index] = op(a, b, index);
  }
  return out;
}
