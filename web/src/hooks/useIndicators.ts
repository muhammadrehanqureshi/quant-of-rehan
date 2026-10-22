/**
 * Indicator state, persisted per browser.
 *
 * Storage is untrusted input: a stale or hand-edited entry is validated
 * field by field, unknown types are dropped, and missing parameters fall back
 * to the definition's defaults. A corrupt entry can therefore never stop the
 * chart from drawing.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createIndicator,
  defaultParams,
  definitionFor,
  initialIndicators,
} from "../indicators/registry";
import type { IndicatorPlacement, IndicatorSpec } from "../indicators/types";

const STORAGE_KEY = "charts-indicators-v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cleanParams(
  type: string,
  raw: unknown,
): Record<string, number | string> {
  const params = defaultParams(type);
  if (!isRecord(raw)) {
    return params;
  }
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === "string") {
      params[key] = value;
    } else if (typeof value === "number" && Number.isFinite(value)) {
      params[key] = value;
    }
  }
  return params;
}

function cleanPlacement(value: unknown): IndicatorPlacement | undefined {
  return value === "pane" || value === "overlay" ? value : undefined;
}

function readStored(): IndicatorSpec[] {
  if (typeof window === "undefined") {
    return initialIndicators();
  }
  let raw: unknown;
  try {
    const text = window.localStorage.getItem(STORAGE_KEY);
    if (text === null) {
      return initialIndicators();
    }
    raw = JSON.parse(text);
  } catch {
    return initialIndicators();
  }
  if (!Array.isArray(raw)) {
    return initialIndicators();
  }
  const seen = new Set<string>();
  const specs: IndicatorSpec[] = [];
  for (const item of raw) {
    if (!isRecord(item)) {
      continue;
    }
    const type = typeof item["type"] === "string" ? item["type"] : "";
    const id = typeof item["id"] === "string" ? item["id"] : "";
    if (definitionFor(type) === undefined || id.length === 0 ||
        seen.has(id)) {
      continue;
    }
    seen.add(id);
    const placement = cleanPlacement(item["placement"]);
    specs.push({
      id,
      type,
      params: cleanParams(type, item["params"]),
      color: typeof item["color"] === "string" ? item["color"] : "#6ea8fe",
      visible: item["visible"] !== false,
      ...(placement === undefined ? {} : { placement }),
    });
  }
  return specs;
}

export interface IndicatorController {
  readonly specs: readonly IndicatorSpec[];
  readonly add: (type: string) => void;
  readonly remove: (id: string) => void;
  readonly update: (id: string, patch: Partial<IndicatorSpec>) => void;
  readonly setParam: (id: string, key: string, value: number | string) => void;
  readonly toggle: (id: string) => void;
  readonly setColor: (id: string, color: string) => void;
  readonly reset: () => void;
}

export function useIndicators(): IndicatorController {
  const [specs, setSpecs] = useState<IndicatorSpec[]>(readStored);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(specs));
    } catch {
      // A full or disabled storage must never break the chart.
    }
  }, [specs]);

  const add = useCallback((type: string) => {
    const created = createIndicator(type);
    if (created !== null) {
      setSpecs((current) => [...current, created]);
    }
  }, []);

  const remove = useCallback((id: string) => {
    setSpecs((current) => current.filter((item) => item.id !== id));
  }, []);

  const update = useCallback((id: string, patch: Partial<IndicatorSpec>) => {
    setSpecs((current) => current.map((item) =>
      item.id === id ? { ...item, ...patch } : item));
  }, []);

  const setParam = useCallback(
    (id: string, key: string, value: number | string) => {
      setSpecs((current) => current.map((item) =>
        item.id === id
          ? { ...item, params: { ...item.params, [key]: value } }
          : item));
    },
    [],
  );

  const toggle = useCallback((id: string) => {
    setSpecs((current) => current.map((item) =>
      item.id === id ? { ...item, visible: !item.visible } : item));
  }, []);

  const setColor = useCallback((id: string, color: string) => {
    setSpecs((current) => current.map((item) =>
      item.id === id ? { ...item, color } : item));
  }, []);

  const reset = useCallback(() => setSpecs(initialIndicators()), []);

  return useMemo(() => ({
    specs, add, remove, update, setParam, toggle, setColor, reset,
  }), [specs, add, remove, update, setParam, toggle, setColor, reset]);
}
