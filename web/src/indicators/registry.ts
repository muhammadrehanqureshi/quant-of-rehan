/**
 * The indicator catalogue.
 *
 * A definition describes a calculation and its defaults; a spec is one
 * configured instance. Keeping the two separate is what allows unlimited
 * instances of the same indicator with different periods and colours.
 */

import type {
  IndicatorDefinition,
  IndicatorPlacement,
  IndicatorSpec,
  ParamDef,
} from "./types";

const NUMBER = (
  key: string,
  label: string,
  value: number,
  min: number,
  max: number,
  step = 1,
): ParamDef => ({ key, label, kind: "number", default: value, min, max, step });

export const COLORS: readonly string[] = [
  "#6ea8fe", "#d9a13b", "#2fbf71", "#e05252", "#b58cff",
  "#4dd0e1", "#f28e2b", "#9ccc65", "#f06292", "#90a4ae",
];

export const DEFINITIONS: readonly IndicatorDefinition[] = [
  {
    type: "ema",
    label: "EMA",
    description: "Exponential moving average of the close.",
    placement: "overlay",
    params: [NUMBER("period", "period", 20, 1, 500)],
    lines: [{ key: "ema", label: "EMA" }],
  },
  {
    type: "sma",
    label: "SMA",
    description: "Simple moving average of the close.",
    placement: "overlay",
    params: [NUMBER("period", "period", 50, 1, 500)],
    lines: [{ key: "sma", label: "SMA" }],
  },
  {
    type: "vwap",
    label: "VWAP",
    description: "Session-anchored volume weighted average price.",
    placement: "overlay",
    params: [],
    lines: [{ key: "vwap", label: "VWAP" }],
  },
  {
    type: "bollinger",
    label: "Bollinger",
    description: "Middle SMA with upper and lower standard-deviation bands.",
    placement: "overlay",
    params: [
      NUMBER("period", "period", 20, 2, 500),
      NUMBER("mult", "deviations", 2, 0.5, 5, 0.1),
    ],
    lines: [
      { key: "middle", label: "middle" },
      { key: "upper", label: "upper", color: "#8b98ab" },
      { key: "lower", label: "lower", color: "#8b98ab" },
    ],
  },
  {
    type: "donchian",
    label: "Donchian",
    description: "Highest high and lowest low over the chosen window.",
    placement: "overlay",
    params: [NUMBER("period", "period", 20, 2, 500)],
    lines: [
      { key: "upper", label: "upper" },
      { key: "lower", label: "lower" },
    ],
  },
  {
    type: "rsi",
    label: "RSI",
    description: "Wilder's relative strength index, 0 to 100.",
    placement: "pane",
    params: [NUMBER("period", "period", 14, 2, 100)],
    lines: [{ key: "rsi", label: "RSI" }],
  },
  {
    type: "macd",
    label: "MACD",
    description: "EMA spread, its signal line and the histogram.",
    placement: "pane",
    params: [
      NUMBER("fast", "fast", 12, 1, 200),
      NUMBER("slow", "slow", 26, 2, 400),
      NUMBER("signal", "signal", 9, 1, 100),
    ],
    lines: [
      { key: "macd", label: "MACD" },
      { key: "signal", label: "signal", color: "#d9a13b" },
    ],
  },
  {
    type: "atr",
    label: "ATR",
    description: "Average true range, the session's own volatility.",
    placement: "pane",
    params: [NUMBER("period", "period", 14, 2, 200)],
    lines: [{ key: "atr", label: "ATR" }],
  },
  {
    type: "stochastic",
    label: "Stochastic",
    description: "Stochastic oscillator with a smoothed signal line.",
    placement: "pane",
    params: [
      NUMBER("period", "period", 14, 2, 100),
      NUMBER("smooth", "smooth", 3, 1, 50),
    ],
    lines: [
      { key: "k", label: "%K" },
      { key: "d", label: "%D", color: "#d9a13b" },
    ],
  },
  {
    type: "roc",
    label: "Rate of change",
    description: "Percentage change over the chosen lookback.",
    placement: "pane",
    params: [NUMBER("period", "period", 10, 1, 200)],
    lines: [{ key: "roc", label: "ROC %" }],
  },
  {
    type: "obv",
    label: "OBV",
    description: "On-balance volume: cumulative signed volume.",
    placement: "pane",
    params: [],
    lines: [{ key: "obv", label: "OBV" }],
  },
  {
    type: "formula",
    label: "Custom formula",
    description: "Write an indicator with sma/ema/rsi/atr and arithmetic.",
    // A formula is usually an oscillator or a spread. Opening it in its own
    // pane keeps an arbitrary value from silently rescaling the price axis;
    // the reader can still choose "over price" for a moving-average formula.
    placement: "pane",
    params: [{
      key: "expr",
      label: "formula",
      kind: "text",
      default: "ema(close, 20) - ema(close, 50)",
    }],
    lines: [{ key: "value", label: "value" }],
    formula: true,
  },
];

const BY_TYPE = new Map(DEFINITIONS.map((item) => [item.type, item]));

export function definitionFor(type: string): IndicatorDefinition | undefined {
  return BY_TYPE.get(type);
}

export function defaultParams(type: string): Record<string, number | string> {
  const definition = definitionFor(type);
  const params: Record<string, number | string> = {};
  for (const param of definition?.params ?? []) {
    params[param.key] = param.default;
  }
  return params;
}

let counter = 0;

function nextId(type: string): string {
  counter += 1;
  const random = typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `${type}-${random}-${counter}`;
}

export function createIndicator(
  type: string,
  options: {
    id?: string;
    params?: Record<string, number | string>;
    color?: string;
    placement?: IndicatorPlacement;
  } = {},
): IndicatorSpec | null {
  const definition = definitionFor(type);
  if (definition === undefined) {
    return null;
  }
  return {
    id: options.id ?? nextId(type),
    type,
    params: { ...defaultParams(type), ...(options.params ?? {}) },
    color: options.color ?? COLORS[counter % COLORS.length] ?? "#6ea8fe",
    visible: true,
    placement: options.placement ?? definition.placement,
  };
}

/** The two indicators a fresh chart opens with, so the panel is not empty. */
export function initialIndicators(): IndicatorSpec[] {
  const ema = createIndicator("ema", {
    id: "initial-ema-20", params: { period: 20 }, color: COLORS[0] ?? "#6ea8fe",
  });
  const rsi = createIndicator("rsi", {
    id: "initial-rsi-14", params: { period: 14 }, color: COLORS[4] ?? "#b58cff",
  });
  return [ema, rsi].filter((item): item is IndicatorSpec => item !== null);
}

export function placementOf(spec: IndicatorSpec): IndicatorPlacement {
  if (spec.type === "formula") {
    return spec.placement === "pane" ? "pane" : "overlay";
  }
  return definitionFor(spec.type)?.placement ?? "overlay";
}

export function numericParam(
  spec: IndicatorSpec,
  key: string,
  fallback: number,
): number {
  const raw = spec.params[key];
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function textParam(
  spec: IndicatorSpec,
  key: string,
  fallback: string,
): string {
  const raw = spec.params[key];
  return typeof raw === "string" && raw.trim().length > 0 ? raw : fallback;
}
