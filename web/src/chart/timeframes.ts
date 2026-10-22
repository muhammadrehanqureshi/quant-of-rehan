/**
 * The timeframe labels the toolbar offers.
 *
 * The server owns which rungs exist; this module only gives them the names a
 * reader expects and groups them so a phone-sized toolbar can present twelve
 * choices without turning into a wall of chips.
 */

import { RESOLUTIONS, type Resolution } from "../api/types";

export interface TimeframeOption {
  readonly id: Resolution;
  readonly label: string;
  readonly short: string;
  readonly group: "seconds" | "minutes" | "hours" | "days";
}

const LABELS: Record<string, { label: string; short: string;
  group: TimeframeOption["group"] }> = {
  "1s": { label: "1 second", short: "1s", group: "seconds" },
  "10s": { label: "10 seconds", short: "10s", group: "seconds" },
  "1m": { label: "1 minute", short: "1m", group: "minutes" },
  "5m": { label: "5 minutes", short: "5m", group: "minutes" },
  "10m": { label: "10 minutes", short: "10m", group: "minutes" },
  "15m": { label: "15 minutes", short: "15m", group: "minutes" },
  "30m": { label: "30 minutes", short: "30m", group: "minutes" },
  "1h": { label: "1 hour", short: "1h", group: "hours" },
  "4h": { label: "4 hours", short: "4h", group: "hours" },
  "1D": { label: "1 day", short: "1D", group: "days" },
  "1W": { label: "1 week", short: "1W", group: "days" },
  "1M": { label: "1 month", short: "1M", group: "days" },
};

export const TIMEFRAMES: readonly TimeframeOption[] = RESOLUTIONS.map((id) => {
  const found = LABELS[id];
  return found === undefined
    ? { id, label: id, short: id, group: "minutes" }
    : { id, ...found };
});

export const TIMEFRAME_GROUPS: ReadonlyArray<{
  readonly key: TimeframeOption["group"];
  readonly label: string;
}> = [
  { key: "seconds", label: "seconds" },
  { key: "minutes", label: "minutes" },
  { key: "hours", label: "hours" },
  { key: "days", label: "days" },
];

export function timeframeLabel(resolution: Resolution): string {
  return LABELS[resolution]?.label ?? resolution;
}

export function timeframeShort(resolution: Resolution): string {
  return LABELS[resolution]?.short ?? resolution;
}

/** How wide one bar is, in milliseconds, for display-only folding. */
export function timeframeMs(resolution: Resolution): number {
  switch (resolution) {
    case "1s": return 1_000;
    case "10s": return 10_000;
    case "1m": return 60_000;
    case "5m": return 300_000;
    case "10m": return 600_000;
    case "15m": return 900_000;
    case "30m": return 1_800_000;
    case "1h": return 3_600_000;
    case "4h": return 14_400_000;
    case "1D":
    case "1d": return 86_400_000;
    case "1W": return 604_800_000;
    case "1M": return 2_592_000_000;
    case "session": return 86_400_000;
  }
}
