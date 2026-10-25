/**
 * The indicator strip, above the chart.
 *
 * TradingView puts its studies in a row under the toolbar, not in a column
 * beside the candles: the chart is what a reader is looking at, so the
 * controls for it belong across the top where they cost no chart width.
 * One chip per configured instance - colour, name, on/off, remove - and the
 * chip's name opens that indicator's own settings dialog, where its inputs
 * and its formula (however long the script) are edited.
 *
 * A formula that does not parse says so on its chip, with the parser's own
 * sentence, so a broken line is never a silent blank on the chart.
 */

import { useMemo, useState } from "react";

import type { IndicatorController } from "../hooks/useIndicators";
import { FormulaError, validateFormula } from "../indicators/expression";
import { DEFINITIONS, definitionFor } from "../indicators/registry";
import type { IndicatorSpec } from "../indicators/types";

export interface IndicatorsPanelProps {
  readonly controller: IndicatorController;
  /** Opening an indicator's own settings dialog, as the legend does on TV. */
  readonly onOpen?: (id: string) => void;
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

export function IndicatorsPanel(
  { controller, onOpen }: IndicatorsPanelProps,
) {
  const { specs, add, remove, toggle, setColor, reset } = controller;
  const [adding, setAdding] = useState("ema");

  const errors = useMemo(() => {
    const map = new Map<string, string>();
    for (const spec of specs) {
      const message = formulaError(spec);
      if (message !== null) {
        map.set(spec.id, message);
      }
    }
    return map;
  }, [specs]);

  return (
    <section className="indicators" aria-label="indicators">
      <div className="indicators__head">
        <h2 className="indicators__title">Indicators</h2>
        <label className="visually-hidden" htmlFor="indicator-type">indicator type</label>
        <select
          id="indicator-type"
          className="indicators__select"
          value={adding}
          onChange={(event) => setAdding(event.target.value)}
        >
          {DEFINITIONS.map((definition) => (
            <option key={definition.type} value={definition.type}>
              {definition.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="indicators__add"
          onClick={() => add(adding)}
        >
          add
        </button>
        <span className="indicators__count" title="indicators on this chart">
          {specs.length}
        </span>
        <button type="button" className="indicators__reset" onClick={reset}>
          reset
        </button>
      </div>

      {specs.length === 0 ? (
        <p className="indicators__quiet">
          No indicators yet. Add as many as you need; overlays share the price
          scale and pane indicators stack in their own panes.
        </p>
      ) : (
        <ul className="indicators__list">
          {specs.map((spec) => {
            const definition = definitionFor(spec.type);
            const error = errors.get(spec.id);
            if (definition === undefined) {
              return (
                <li key={spec.id} className="indicator indicator--broken">
                  <span>{spec.type} is unknown to this build.</span>
                  <button type="button" onClick={() => remove(spec.id)}>remove</button>
                </li>
              );
            }
            const classes = ["indicator"];
            if (!spec.visible) {
              classes.push("indicator--off");
            }
            if (error !== undefined) {
              classes.push("indicator--error");
            }
            return (
              <li key={spec.id} className={classes.join(" ")}>
                <input
                  type="color"
                  className="indicator__dot"
                  value={spec.color}
                  aria-label={`${definition.label} colour`}
                  title="Line colour"
                  onChange={(event) => setColor(spec.id, event.target.value)}
                />
                <button
                  type="button"
                  className="indicator__title"
                  title={error ?? `${definition.description} - open the settings`}
                  onClick={() => onOpen?.(spec.id)}
                >
                  {definition.label}
                  {spec.placement === "pane" ? (
                    <span className="indicator__pane" aria-hidden="true">pane</span>
                  ) : null}
                </button>
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
                  aria-label={`remove ${definition.label}`}
                  title={`remove ${definition.label}`}
                  onClick={() => remove(spec.id)}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {errors.size > 0 ? (
        <p className="indicator__error" role="status">
          {[...errors.values()][0]}
        </p>
      ) : null}
    </section>
  );
}
