/**
 * The indicator contract.
 *
 * An indicator is a definition (what it needs and what it draws) plus a spec
 * (one configured instance). Unlimited instances are allowed: the engine
 * computes each one independently and the renderer stacks overlays on the
 * price pane and panes beneath it. Nothing here touches React or the DOM, so
 * every calculation is testable without a browser.
 */

export type IndicatorPlacement = "overlay" | "pane";

export interface ParamDef {
  readonly key: string;
  readonly label: string;
  readonly kind: "number" | "text";
  readonly default: number | string;
  readonly min?: number;
  readonly max?: number;
  readonly step?: number;
}

export interface LineDef {
  readonly key: string;
  readonly label: string;
  readonly color?: string;
}

export interface IndicatorDefinition {
  readonly type: string;
  readonly label: string;
  readonly description: string;
  readonly placement: IndicatorPlacement;
  readonly params: readonly ParamDef[];
  readonly lines: readonly LineDef[];
  /** The formula editor supplies its own expression and placement. */
  readonly formula?: boolean;
}

/** One configured indicator. `id` is unique even for repeated types. */
export interface IndicatorSpec {
  readonly id: string;
  readonly type: string;
  readonly params: Readonly<Record<string, number | string>>;
  readonly color: string;
  readonly visible: boolean;
  /** Formula instances only; a definition's own placement otherwise. */
  readonly placement?: IndicatorPlacement;
}

export interface IndicatorLine {
  readonly key: string;
  readonly label: string;
  readonly color: string;
  /** NaN marks a bar where the indicator is not yet defined. */
  readonly values: Float64Array;
}

export interface IndicatorHistogram {
  readonly values: Float64Array;
  readonly positive: string;
  readonly negative: string;
}

export interface IndicatorOutput {
  readonly id: string;
  readonly type: string;
  readonly label: string;
  readonly placement: IndicatorPlacement;
  readonly lines: readonly IndicatorLine[];
  readonly histogram?: IndicatorHistogram;
  /** Fixed pane range (RSI 0-100), or null for an automatic fit. */
  readonly range?: readonly [number, number] | null;
  readonly error?: string;
}

/** The columns the engine reads; a copy, so an indicator cannot mutate bars. */
export interface SeriesData {
  readonly length: number;
  readonly time: Float64Array;
  readonly open: Float64Array;
  readonly high: Float64Array;
  readonly low: Float64Array;
  readonly close: Float64Array;
  readonly volume: Float64Array;
}
