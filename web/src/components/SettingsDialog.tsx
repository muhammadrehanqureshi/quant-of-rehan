/**
 * The settings dialogs, in TradingView's shape.
 *
 * A floating modal with tabs, opened from the chart itself: the gear opens
 * the chart's own settings (colours, grid, watermark), and an indicator's
 * title opens its settings (Inputs on the first tab, Styles on the second).
 * Escape or a click on the haze closes either one; nothing inside mutates
 * state except through the callbacks the app passes in, so a closed dialog
 * can never leave half a change behind.
 */

import { useEffect, useRef, useState } from "react";

import type { IndicatorController } from "../hooks/useIndicators";
import type { ChartAppearance } from "../hooks/useAppearance";
import { FormulaError, validateFormula } from "../indicators/expression";
import type {
  IndicatorDefinition,
  IndicatorSpec,
  ParamDef,
} from "../indicators/types";

export interface ModalProps {
  readonly title: string;
  readonly onClose: () => void;
  readonly children: React.ReactNode;
}

/** The haze-and-panel shell both dialogs share. */
export function Dialog({ title, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    const first = ref.current?.querySelector<HTMLElement>(
      "input, select, textarea, button",
    );
    first?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="settings-haze" role="presentation"
         onClick={(event) => {
           if (event.target === event.currentTarget) {
             onClose();
           }
         }}>
      <div className="settings-dialog" role="dialog" aria-label={title}
           ref={ref}>
        <header className="settings-dialog__head">
          <h2>{title}</h2>
          <button type="button" className="settings-dialog__close"
                  aria-label="close the settings"
                  onClick={onClose}>
            ×
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

export interface ChartSettingsProps {
  readonly appearance: ChartAppearance;
  readonly onAppearance: (patch: {
    up?: string;
    down?: string;
    gridOn?: boolean;
    watermarkOn?: boolean;
  }) => void;
  /** The dialog's own reset, back to TV's dark defaults. */
  readonly onReset: () => void;
  readonly onClose: () => void;
}

/** The chart's own settings: colours, grid, watermark. */
export function ChartSettingsDialog(props: ChartSettingsProps) {
  const { appearance, onAppearance, onReset, onClose } = props;
  return (
    <Dialog title="Chart settings" onClose={onClose}>
      <div className="settings-dialog__body">
        <label className="settings-row">
          <span>up colour</span>
          <input type="color" value={appearance.up} aria-label="up colour"
                 onChange={(event) => onAppearance({ up: event.target.value })} />
        </label>
        <label className="settings-row">
          <span>down colour</span>
          <input type="color" value={appearance.down} aria-label="down colour"
                 onChange={(event) => onAppearance({ down: event.target.value })} />
        </label>
        <label className="settings-row settings-row--check">
          <span>grid lines</span>
          <input type="checkbox" checked={appearance.gridOn}
                 aria-label="grid lines"
                 onChange={(event) =>
                   onAppearance({ gridOn: event.target.checked })} />
        </label>
        <label className="settings-row settings-row--check">
          <span>symbol watermark</span>
          <input type="checkbox" checked={appearance.watermarkOn}
                 aria-label="symbol watermark"
                 onChange={(event) =>
                   onAppearance({ watermarkOn: event.target.checked })} />
        </label>
      </div>
      <footer className="settings-dialog__foot">
        <button type="button" onClick={onReset}>reset defaults</button>
        <span className="settings-dialog__note">
          saved per browser · the tape stays untouched
        </span>
      </footer>
    </Dialog>
  );
}

export interface IndicatorSettingsProps {
  readonly spec: IndicatorSpec;
  readonly definition: IndicatorDefinition | undefined;
  readonly controller: Pick<
    IndicatorController,
    "setParam" | "setColor" | "toggle" | "update" | "remove"
  >;
  readonly onClose: () => void;
}

function paramValue(spec: IndicatorSpec, param: ParamDef): string {
  const value = spec.params[param.key];
  return value === undefined ? String(param.default) : String(value);
}

/** An indicator's settings: Inputs, then Styles, as TV lays them out. */
export function IndicatorSettingsDialog(props: IndicatorSettingsProps) {
  const { spec, definition, controller, onClose } = props;
  const [tab, setTab] = useState<"inputs" | "styles">( definition?.params.length ? "inputs" : "styles");

  const formulaError = (() => {
    if (!definition?.formula) {
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
  })();

  return (
    <Dialog
      title={definition === undefined ? "Indicator" : definition.label}
      onClose={onClose}
    >
      <div className="settings-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "inputs"}
                className={tab === "inputs" ? "settings-tab settings-tab--on"
                  : "settings-tab"}
                onClick={() => setTab("inputs")}
                disabled={definition === undefined
                  || definition.params.length === 0}>
          Inputs
        </button>
        <button type="button" role="tab" aria-selected={tab === "styles"}
                className={tab === "styles" ? "settings-tab settings-tab--on"
                  : "settings-tab"}
                onClick={() => setTab("styles")}>
          Styles
        </button>
      </div>

      <div className="settings-dialog__body">
        {tab === "inputs" && definition !== undefined ? (
          definition.params.length === 0
            ? <p className="settings-dialog__note">
                this indicator has no inputs.
              </p>
            : definition.params.map((param) => (
              <label key={param.key} className="settings-row">
                <span>{param.label}</span>
                {param.kind === "number" ? (
                  <input
                    type="number"
                    value={paramValue(spec, param)}
                    min={param.min ?? 1}
                    max={param.max ?? 1000}
                    step={param.step ?? 1}
                    onChange={(event) =>
                      controller.setParam(spec.id, param.key,
                        event.target.value)}
                  />
                ) : (
                  <textarea
                    rows={definition?.formula ? 12 : 3}
                    spellCheck={false}
                    aria-label={param.label}
                    value={paramValue(spec, param)}
                    onChange={(event) =>
                      controller.setParam(spec.id, param.key,
                        event.target.value)}
                  />
                )}
              </label>
            ))
        ) : (
          <>
            <label className="settings-row">
              <span>line colour</span>
              <input type="color" value={spec.color} aria-label="line colour"
                     onChange={(event) =>
                       controller.setColor(spec.id, event.target.value)} />
            </label>
            <label className="settings-row settings-row--check">
              <span>visible on the chart</span>
              <input type="checkbox" checked={spec.visible}
                     aria-label="visible on the chart"
                     onChange={() => controller.toggle(spec.id)} />
            </label>
            {definition?.formula ? (
              <label className="settings-row">
                <span>draw</span>
                <select
                  value={spec.placement ?? "overlay"}
                  onChange={(event) =>
                    controller.update(spec.id, {
                      placement: event.target.value === "pane"
                        ? "pane" : "overlay",
                    })}
                >
                  <option value="overlay">over price</option>
                  <option value="pane">own pane</option>
                </select>
              </label>
            ) : null}
          </>
        )}
        {definition?.formula ? (
          <p className="settings-dialog__note">
            One statement per line: series (open, high, low, close, volume,
            hl2, ohlc4), functions (sma, ema, rsi, atr, stddev, highest,
            lowest, roc, change, obv, abs, sqrt, log, exp, min, max, nz,
            plot), arithmetic, and `name = expression` lines. A script may be
            up to 8,000 characters; its last line is what the chart draws.
          </p>
        ) : null}
        {formulaError !== null
          ? <p className="indicator__error" role="status">{formulaError}</p>
          : null}
      </div>

      <footer className="settings-dialog__foot">
        <button type="button" className="settings-dialog__remove"
                onClick={() => {
                  controller.remove(spec.id);
                  onClose();
                }}>
          remove indicator
        </button>
      </footer>
    </Dialog>
  );
}
