/**
 * A complete, runnable chart with custom indicators.
 *
 * Copy this file into an application and mount `<CustomChart />`; it expects
 * the chart service to be reachable on the same origin. It is deliberately
 * not imported by `App.tsx`: the main terminal has its own indicator state,
 * while this file is the smallest honest example of initialising a chart with
 * a fixed set of overlays and a formula pane.
 *
 * The important part is that indicators are *specs*, not definitions. The same
 * `ema` definition can appear any number of times with different periods and
 * colours, and the formula spec is ordinary data, so it is persisted and
 * edited like every other instance.
 */

import { useMemo } from "react";

import { ChartClient } from "../api/client";
import { ChartCanvas } from "../components/ChartCanvas";
import { useChartFeed } from "../hooks/useChartFeed";
import { createIndicator } from "../indicators/registry";
import type { IndicatorSpec } from "../indicators/types";

const CUSTOM_INDICATORS: readonly IndicatorSpec[] = [
  createIndicator("ema", {
    id: "example-ema-9",
    params: { period: 9 },
    color: "#4dd0e1",
  }),
  createIndicator("bollinger", {
    id: "example-bands-20",
    params: { period: 20, mult: 2 },
    color: "#b58cff",
  }),
  createIndicator("formula", {
    id: "example-momentum-10",
    params: { expr: "roc(close, 10)" },
    color: "#d9a13b",
    placement: "pane",
  }),
].filter((spec): spec is IndicatorSpec => spec !== null);

export function CustomChart() {
  const client = useMemo(() => new ChartClient(), []);
  const feed = useChartFeed(client, "KSE100", "5m");
  const session = feed.meta.session;

  return (
    <section
      aria-label="KSE100 with custom indicators"
      style={{ display: "grid", gap: "8px", height: "100%" }}
    >
      <div style={{ display: "flex", gap: "12px", fontSize: "12px" }}>
        <strong>KSE100</strong>
        <span>5 minutes</span>
        <span>{feed.status}</span>
        <span>{feed.meta.payload?.bar_count ?? 0} bars</span>
      </div>
      <div style={{ minHeight: "420px", display: "grid" }}>
        <ChartCanvas
          series={feed.series}
          gaps={feed.meta.gaps}
          resolution="5m"
          viewKey="example|KSE100|5m"
          version={feed.version}
          volumeAvailable={session?.volume_available ?? false}
          sessionLabel={
            session === null
              ? "No session reported."
              : `${session.day}${session.archived ? ", stored session" : ""}.`
          }
          emptyNote={
            session?.note ||
            "No bars for KSE100 in this session yet; this is missing data, not a price of zero."
          }
          indicators={CUSTOM_INDICATORS}
        />
      </div>
      {feed.error === null ? null : (
        <p role="alert" style={{ margin: 0 }}>
          {feed.error.category}: {feed.error.detail}
        </p>
      )}
    </section>
  );
}
