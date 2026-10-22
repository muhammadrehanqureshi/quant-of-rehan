/**
 * The indicator engine: specs plus bars in, drawable lines and panes out.
 *
 * It is deliberately pure. The renderer gets Float64Arrays and never asks an
 * indicator to run during a pointer move; the canvas component caches the
 * result of this module per bar version.
 */

import type { ColumnSeries } from "../chart/series";
import { compileFormula, FormulaError } from "./expression";
import {
  atr,
  ema,
  filled,
  highest,
  lowest,
  obv,
  rateOfChange,
  rsi,
  sma,
  standardDeviation,
  vwap,
} from "./math";
import {
  definitionFor,
  numericParam,
  placementOf,
  textParam,
} from "./registry";
import type {
  IndicatorLine,
  IndicatorOutput,
  IndicatorSpec,
  SeriesData,
} from "./types";

export function seriesData(series: ColumnSeries): SeriesData {
  const columns = series.columns();
  return { length: series.length, ...columns };
}

function line(
  key: string,
  label: string,
  color: string,
  values: Float64Array,
): IndicatorLine {
  return { key, label, color, values };
}

function labelOf(spec: IndicatorSpec): string {
  const definition = definitionFor(spec.type);
  const base = definition?.label ?? spec.type;
  switch (spec.type) {
    case "sma":
    case "ema":
    case "rsi":
    case "atr":
    case "roc":
      return `${base} ${Math.round(numericParam(spec, "period", 20))}`;
    case "bollinger":
      return `${base} ${Math.round(numericParam(spec, "period", 20))}`;
    case "donchian":
      return `${base} ${Math.round(numericParam(spec, "period", 20))}`;
    case "macd":
      return `${base} ${Math.round(numericParam(spec, "fast", 12))}/` +
        `${Math.round(numericParam(spec, "slow", 26))}/` +
        `${Math.round(numericParam(spec, "signal", 9))}`;
    case "stochastic":
      return `${base} ${Math.round(numericParam(spec, "period", 14))}`;
    case "formula":
      return "Formula";
    default:
      return base;
  }
}

function computeOne(spec: IndicatorSpec, data: SeriesData): IndicatorOutput {
  const definition = definitionFor(spec.type);
  if (definition === undefined) {
    return {
      id: spec.id, type: spec.type, label: spec.type, placement: "overlay",
      lines: [], error: `unknown indicator "${spec.type}"`,
    };
  }
  const placement = placementOf(spec);
  const label = labelOf(spec);
  const colour = spec.color;
  const period = (key: string, fallback: number, minimum = 1): number =>
    Math.max(minimum, Math.round(numericParam(spec, key, fallback)));

  try {
    switch (spec.type) {
      case "sma": {
        const values = sma(data.close, period("period", 50));
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("sma", label, colour, values)],
        };
      }
      case "ema": {
        const values = ema(data.close, period("period", 20));
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("ema", label, colour, values)],
        };
      }
      case "vwap": {
        const values = vwap(data.time, data.high, data.low, data.close,
          data.volume);
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("vwap", label, colour, values)],
        };
      }
      case "bollinger": {
        const window = period("period", 20, 2);
        const mult = Math.max(0.1, numericParam(spec, "mult", 2));
        const middle = sma(data.close, window);
        const deviation = standardDeviation(data.close, window);
        const upper = filled(data.length);
        const lower = filled(data.length);
        for (let index = 0; index < data.length; index += 1) {
          const base = middle[index] ?? Number.NaN;
          const spread = deviation[index] ?? Number.NaN;
          if (Number.isFinite(base) && Number.isFinite(spread)) {
            upper[index] = base + spread * mult;
            lower[index] = base - spread * mult;
          }
        }
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [
            line("middle", `${label} mid`, colour, middle),
            line("upper", "upper", "#8b98ab", upper),
            line("lower", "lower", "#8b98ab", lower),
          ],
        };
      }
      case "donchian": {
        const window = period("period", 20, 2);
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [
            line("upper", "upper", colour, highest(data.high, window)),
            line("lower", "lower", colour, lowest(data.low, window)),
          ],
        };
      }
      case "rsi": {
        const values = rsi(data.close, period("period", 14, 2));
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("rsi", label, colour, values)],
          range: [0, 100],
        };
      }
      case "macd": {
        const fast = period("fast", 12);
        const slow = Math.max(fast + 1, period("slow", 26));
        const signalPeriod = period("signal", 9);
        const fastLine = ema(data.close, fast);
        const slowLine = ema(data.close, slow);
        const macd = filled(data.length);
        for (let index = 0; index < data.length; index += 1) {
          const a = fastLine[index] ?? Number.NaN;
          const b = slowLine[index] ?? Number.NaN;
          if (Number.isFinite(a) && Number.isFinite(b)) {
            macd[index] = a - b;
          }
        }
        const signal = ema(macd, signalPeriod);
        const histogram = filled(data.length);
        for (let index = 0; index < data.length; index += 1) {
          const a = macd[index] ?? Number.NaN;
          const b = signal[index] ?? Number.NaN;
          if (Number.isFinite(a) && Number.isFinite(b)) {
            histogram[index] = a - b;
          }
        }
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [
            line("macd", "MACD", colour, macd),
            line("signal", "signal", "#d9a13b", signal),
          ],
          histogram: {
            values: histogram,
            positive: "#2fbf71",
            negative: "#e05252",
          },
        };
      }
      case "atr": {
        const values = atr(data.high, data.low, data.close,
          period("period", 14, 2));
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("atr", label, colour, values)],
        };
      }
      case "stochastic": {
        const window = period("period", 14, 2);
        const smooth = period("smooth", 3);
        const high = highest(data.high, window);
        const low = lowest(data.low, window);
        const k = filled(data.length);
        for (let index = 0; index < data.length; index += 1) {
          const top = high[index] ?? Number.NaN;
          const bottom = low[index] ?? Number.NaN;
          const close = data.close[index] ?? Number.NaN;
          if (Number.isFinite(top) && Number.isFinite(bottom) &&
              top !== bottom) {
            k[index] = ((close - bottom) / (top - bottom)) * 100;
          }
        }
        const d = sma(k, smooth);
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [
            line("k", "%K", colour, k),
            line("d", "%D", "#d9a13b", d),
          ],
          range: [0, 100],
        };
      }
      case "roc": {
        const values = rateOfChange(data.close, period("period", 10));
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("roc", label, colour, values)],
        };
      }
      case "obv": {
        const values = obv(data.close, data.volume);
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("obv", label, colour, values)],
        };
      }
      case "formula": {
        const source = textParam(spec, "expr",
          "ema(close, 20) - ema(close, 50)");
        const values = compileFormula(source)(data);
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [line("value", label, colour, values)],
        };
      }
      default:
        return {
          id: spec.id, type: spec.type, label, placement,
          lines: [], error: `indicator "${spec.type}" has no calculator`,
        };
    }
  } catch (error) {
    return {
      id: spec.id, type: spec.type, label, placement, lines: [],
      error: error instanceof FormulaError || error instanceof Error
        ? error.message
        : String(error),
    };
  }
}

export function computeIndicators(
  specs: readonly IndicatorSpec[],
  data: SeriesData,
): IndicatorOutput[] {
  return specs
    .filter((spec) => spec.visible)
    .map((spec) => computeOne(spec, data));
}

export function outputsFor(
  outputs: readonly IndicatorOutput[],
  placement: "overlay" | "pane",
): IndicatorOutput[] {
  return outputs.filter((output) => output.placement === placement &&
    output.error === undefined);
}
