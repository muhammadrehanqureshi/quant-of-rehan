/**
 * The chart's appearance settings, persisted per browser.
 *
 * TradingView's settings dialog changes how the chart is drawn, not what is
 * drawn. This state is exactly that: the candle colours and whether the grid
 * lines show. Storage is untrusted, so every field is checked before it
 * reaches the chart, and a corrupt entry falls back to TV's own dark values.
 */

import { useCallback, useEffect, useState } from "react";

export interface ChartAppearance {
  /** Bull candle body and wick. */
  readonly up: string;
  /** Bear candle body and wick. */
  readonly down: string;
  /** The engine's background grid lines, on by default as TV draws it. */
  readonly gridOn: boolean;
  /** The symbol/timeframe watermark behind the price pane. */
  readonly watermarkOn: boolean;
}

export const DEFAULT_APPEARANCE: ChartAppearance = {
  up: "#089981",
  down: "#f23645",
  gridOn: true,
  watermarkOn: true,
};

const STORAGE_KEY = "charts-appearance-v1";

function hexColor(value: unknown, fallback: string): string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)
    ? value
    : fallback;
}

function readStored(): ChartAppearance {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) {
      return DEFAULT_APPEARANCE;
    }
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) {
      return DEFAULT_APPEARANCE;
    }
    const record = parsed as Record<string, unknown>;
    return {
      up: hexColor(record["up"], DEFAULT_APPEARANCE.up),
      down: hexColor(record["down"], DEFAULT_APPEARANCE.down),
      gridOn: record["gridOn"] !== false,
      watermarkOn: record["watermarkOn"] !== false,
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export type AppearancePatch = Partial<Omit<ChartAppearance, "up" | "down">> & {
  readonly up?: unknown;
  readonly down?: unknown;
};

export function useAppearance(): [
  ChartAppearance,
  (patch: AppearancePatch) => void,
  () => void,
] {
  const [appearance, setAppearance] = useState<ChartAppearance>(readStored);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
    } catch {
      // A full or disabled storage must never break the chart.
    }
  }, [appearance]);

  const update = useCallback((patch: AppearancePatch) => {
    setAppearance((current) => ({
      up: hexColor(patch.up, current.up),
      down: hexColor(patch.down, current.down),
      gridOn: patch.gridOn ?? current.gridOn,
      watermarkOn: patch.watermarkOn ?? current.watermarkOn,
    }));
  }, []);

  const reset = useCallback(() => setAppearance(DEFAULT_APPEARANCE), []);

  return [appearance, update, reset];
}
