/**
 * The indicator panel.
 *
 * One row per configured instance, no cap on how many. Each row edits its own
 * parameters, colour, visibility and (for formulas) whether it draws over the
 * price or in its own pane. The formula editor validates syntax as you type,
 * so a broken expression is a sentence in the panel rather than a blank line
 * on the chart.
 */

import { useMemo, useState } from "react";

import type { IndicatorController } from "../hooks/useIndicators";
import { FormulaError, validateFormula } from "../indicators/expression";
import { DEFINITIONS, definitionFor } from "../indicators/registry";
import type { IndicatorSpec, ParamDef } from "../indicators/types";

export interface IndicatorsPanelProps {
  readonly controller: IndicatorController;
}

function paramValue(spec: IndicatorSpec, param: ParamDef): string {
  const value = spec.params[param.key];
  return value === undefined ? String(param.default) : String(value);
}

function formulaError(spec: IndicatorSpec): string | null {
  if (spec.type !== "formula") {
    return null;
  }
  const raw = spec.params["expr"];
  const source = typeof raw === "string" ? raw : String(raw ?? "");
  try {
    validateFormula(source);
    return null;
  } catch (error) {
    return error instanceof FormulaError || error instanceof Error
      ? error.message
      : String(error);
  }
}

export function IndicatorsPanel({ controller }: IndicatorsPanelProps) {
  const { specs, add, remove, update, setParam, toggle, setColor, reset } =
    controller;
  const [adding, setAdding] = useState("ema");

  const errors = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const spec of specs) {
      map.set(spec.id, formulaError(spec));
    }
    return map;
  }, [specs]);

  return (
    <aside className="indicators" aria-label="indicators">
      <div className="indicators__head">
        <h2>Indicators</h2>
        <span className="indicators__count">{specs.length}</span>
      </div>

      <div className="indicators__add">
        <label className="visually-hidden" htmlFor="indicator-type">indicator type</label>
        <select
          id="indicator-type"
          value={adding}
          onChange={(event) => setAdding(event.target.value)}
        >
          {DEFINITIONS.map((definition) => (
            <option key={definition.type} value={definition.type}>
              {definition.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => add(adding)}>add</button>
      </div>

      {specs.length === 0 ? (
        <p className="indicators__quiet">
          No indicators yet. Add as many as you need; overlays share the price
          scale and pane indicators stack beneath the volume.
        </p>
      ) : (
        <ul className="indicators__list">
          {specs.map((spec) => {
            const definition = definitionFor(spec.type);
            const error = errors.get(spec.id) ?? null;
            if (definition === undefined) {
              return (
                <li key={spec.id} className="indicator indicator--broken">
                  <span>{spec.type} is unknown to this build.</span>
                  <button type="button" onClick={() => remove(spec.id)}>remove</button>
                </li>
              );
            }
            return (
              <li key={spec.id}
                  className={spec.visible ? "indicator" : "indicator indicator--off"}>
                <div className="indicator__head">
                  <input
                    type="color"
                    className="indicator__colour"
                    value={spec.color}
                    aria-label={`${definition.label} colour`}
                    title="Line colour"
                    onChange={(event) => setColor(spec.id, event.target.value)}
                  />
                  <span className="indicator__title">{definition.label}</span>
                  <button
                    type="button"
                    className="indicator__icon"
                    aria-pressed={spec.visible}
                    title={spec.visible ? "Hide this indicator" : "Show this indicator"}
                    onClick={() => toggle(spec.id)}
                  >
                    {spec.visible ? "on" : "off"}
                  </button>
                  <button
                    type="button"
                    className="indicator__icon"
                    title="Remove this indicator"
                    aria-label={`remove ${definition.label}`}
                    onClick={() => remove(spec.id)}
                  >
                    ×
                  </button>
                </div>

                <p className="indicator__description">{definition.description}</p>

                <div className="indicator__params">
                  {definition.params.map((param) => (
                    <label key={param.key} className="indicator__param">
                      <span>{param.label}</span>
                      {param.kind === "number" ? (
                        <input
                          type="number"
                          value={paramValue(spec, param)}
                          min={param.min ?? 1}
                          max={param.max ?? 1000}
                          step={param.step ?? 1}
                          onChange={(event) =>
                            setParam(spec.id, param.key, event.target.value)}
                        />
                      ) : (
                        <textarea
                          rows={2}
                          spellCheck={false}
                          value={paramValue(spec, param)}
                          onChange={(event) =>
                            setParam(spec.id, param.key, event.target.value)}
                        />
                      )}
                    </label>
                  ))}
                </div>

                {definition.formula ? (
                  <>
                    <label className="indicator__param indicator__param--row">
                      <span>draw</span>
                      <select
                        value={spec.placement ?? "overlay"}
                        onChange={(event) =>
                          update(spec.id, {
                            placement: event.target.value === "pane"
                              ? "pane" : "overlay",
                          })}
                      >
                        <option value="overlay">over price</option>
                        <option value="pane">own pane</option>
                      </select>
                    </label>
                    <p className="indicator__help">
                      sma, ema, rsi, atr, stddev, highest, lowest, roc,
                      change, obv, abs, sqrt, log, exp, min, max, nz.
                      Series: open, high, low, close, volume, hl2, ohlc4.
                    </p>
                  </>
                ) : null}

                {error !== null ? (
                  <p className="indicator__error" role="status">{error}</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <div className="indicators__foot">
        <button type="button" onClick={reset}>reset defaults</button>
        <span className="indicators__quiet">
          overlays are unlimited; up to eight pane indicators are drawn.
        </span>
      </div>
    </aside>
  );
}
