"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";
import { CourtSvg } from "@/components/mdx/court-svg";

export type PlotOptions = Parameters<typeof Plot.plot>[0];

/**
 * Generic Observable Plot wrapper for MDX.
 *
 * Pass any Plot.plot() options object. The chart renders client-side
 * into a ref'd container and cleans up on unmount or options change.
 */
export function ObservablePlot({
  options,
  title,
  caption,
  className,
}: {
  /** Observable Plot options passed directly to Plot.plot() */
  options: PlotOptions;
  /** Optional title above the chart */
  title?: string;
  /** Optional caption below the chart */
  caption?: string;
  /** Additional CSS classes */
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !options) return;

    const plot = Plot.plot({
      ...options,
      style: {
        background: "transparent",
        color: "currentColor",
        fontFamily: "inherit",
        fontSize: "12px",
        ...(typeof options.style === "object" ? options.style : {}),
      },
    });

    containerRef.current.append(plot);
    return () => plot.remove();
  }, [options]);

  return (
    <div className={`nba-viz-shell ${className ?? ""}`}>
      {title ? (
        <div className="nba-viz-toolbar">
          <div>
            <p className="nba-kicker">{title}</p>
            {caption ? (
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {caption}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
      <div ref={containerRef} className="overflow-x-auto px-2 py-3" />
    </div>
  );
}

/** Bare plot renderer without the shell wrapper — used by ShotChart overlay. */
function ObservablePlotInner({ options }: { options: PlotOptions }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !options) return;
    const plot = Plot.plot({
      ...options,
      style: {
        background: "transparent",
        color: "currentColor",
        fontFamily: "inherit",
        fontSize: "12px",
        ...(typeof options.style === "object" ? options.style : {}),
      },
    });
    containerRef.current.append(plot);
    return () => plot.remove();
  }, [options]);

  return <div ref={containerRef} className="size-full" />;
}

/**
 * Pre-configured NBA shot chart component.
 *
 * Renders a dot plot overlaid on an SVG court diagram.
 * Expects data with `loc_x`, `loc_y`, and optional `made` fields.
 */
export function ShotChart({
  data,
  title = "Shot Chart",
  width = 500,
  height = 470,
}: {
  data: Array<{
    loc_x: number;
    loc_y: number;
    made?: boolean;
    [k: string]: unknown;
  }>;
  title?: string;
  width?: number;
  height?: number;
}) {
  const options: PlotOptions = {
    width,
    height,
    x: { domain: [-250, 250], label: null, axis: null },
    y: { domain: [-47.5, 422.5], label: null, axis: null },
    aspectRatio: 1,
    marginTop: 0,
    marginRight: 0,
    marginBottom: 0,
    marginLeft: 0,
    marks: [
      Plot.dot(data, {
        x: "loc_x",
        y: "loc_y",
        fill: (d: { made?: boolean }) => (d.made ? "#00A651" : "#C8102E"),
        fillOpacity: 0.5,
        r: 3,
        tip: true,
      }),
    ],
  };

  return (
    <div className="nba-viz-shell">
      {title ? (
        <div className="nba-viz-toolbar">
          <p className="nba-kicker">{title}</p>
        </div>
      ) : null}
      <div className="relative overflow-hidden" style={{ width, height }}>
        <CourtSvg className="absolute inset-0 size-full" />
        <div className="absolute inset-0">
          <ObservablePlotInner options={options} />
        </div>
      </div>
    </div>
  );
}

/**
 * Pre-configured game flow chart.
 *
 * Renders a line chart of score differential over time.
 * Expects data with `period`, `time`, and `score_diff` fields.
 */
export function GameFlow({
  data,
  title = "Game Flow",
  width = 640,
  height = 300,
}: {
  data: Array<{
    period: number;
    time: number;
    score_diff: number;
    [k: string]: unknown;
  }>;
  title?: string;
  width?: number;
  height?: number;
}) {
  const options: PlotOptions = {
    width,
    height,
    y: { label: "Score Differential", grid: true },
    x: { label: "Game Time" },
    marks: [
      Plot.ruleY([0], { stroke: "#999", strokeDasharray: "4,4" }),
      Plot.line(data, {
        x: "time",
        y: "score_diff",
        stroke: "#1D428A",
        strokeWidth: 2,
        tip: true,
      }),
      Plot.areaY(data, {
        x: "time",
        y: "score_diff",
        fill: (d: { score_diff: number }) =>
          d.score_diff >= 0 ? "#00A65120" : "#C8102E20",
      }),
    ],
  };

  return <ObservablePlot options={options} title={title} />;
}

/**
 * Pre-configured grouped bar chart for comparing players across metrics.
 *
 * Each metric becomes a facet column; bars within each facet represent
 * individual players, coloured by the default categorical scheme.
 */
export function PlayerCompare({
  data,
  title = "Player Comparison",
  width = 640,
  height = 400,
}: {
  data: Array<{
    player: string;
    metric: string;
    value: number;
    [k: string]: unknown;
  }>;
  title?: string;
  width?: number;
  height?: number;
}) {
  const options: PlotOptions = {
    width,
    height,
    fx: { label: null },
    y: { grid: true },
    marks: [
      Plot.barY(data, {
        fx: "metric",
        x: "player",
        y: "value",
        fill: "player",
        tip: true,
      }),
      Plot.ruleY([0]),
    ],
  };

  return <ObservablePlot options={options} title={title} />;
}

/**
 * Pre-configured multi-line chart for season-over-season trends.
 *
 * When a `group` field is present in the data each distinct group
 * is rendered as its own coloured line.
 */
export function SeasonTrend({
  data,
  title = "Season Trend",
  yLabel,
  width = 640,
  height = 300,
}: {
  data: Array<{
    season: string;
    value: number;
    group?: string;
    [k: string]: unknown;
  }>;
  title?: string;
  yLabel?: string;
  width?: number;
  height?: number;
}) {
  const hasGroup = data.some((d) => d.group != null);

  const options: PlotOptions = {
    width,
    height,
    y: { grid: true, label: yLabel },
    marks: [
      Plot.line(data, {
        x: "season",
        y: "value",
        ...(hasGroup ? { stroke: "group" } : { stroke: "#1D428A" }),
        strokeWidth: 2,
        marker: "circle",
        tip: true,
      }),
    ],
  };

  return <ObservablePlot options={options} title={title} />;
}

/**
 * Pre-configured histogram for stat distributions.
 *
 * When a `group` field is present the histogram is stacked by group.
 * Otherwise all bars use NBA blue (#1D428A).
 */
export function DistributionPlot({
  data,
  title = "Distribution",
  xLabel,
  bins = 20,
  width = 640,
  height = 300,
}: {
  data: Array<{
    value: number;
    group?: string;
    [k: string]: unknown;
  }>;
  title?: string;
  xLabel?: string;
  bins?: number;
  width?: number;
  height?: number;
}) {
  const hasGroup = data.some((d) => d.group != null);

  const options: PlotOptions = {
    width,
    height,
    x: { label: xLabel },
    y: { grid: true },
    marks: [
      Plot.rectY(
        data,
        Plot.binX(
          { y: "count" },
          {
            x: "value",
            fill: hasGroup ? "group" : "#1D428A",
            thresholds: bins,
          } as Record<string, unknown>,
        ),
      ),
      Plot.ruleY([0]),
    ],
  };

  return <ObservablePlot options={options} title={title} />;
}

/**
 * Pre-configured 2D cell grid for zone efficiency heatmaps or calendars.
 *
 * Each cell is coloured by `value` using a sequential YlOrRd scale.
 * Cell labels are overlaid in white text showing the value rounded to
 * one decimal place.
 */
export function HeatmapGrid({
  data,
  title = "Heatmap",
  width = 640,
  height = 400,
}: {
  data: Array<{
    x: string;
    y: string;
    value: number;
    [k: string]: unknown;
  }>;
  title?: string;
  width?: number;
  height?: number;
}) {
  const options: PlotOptions = {
    width,
    height,
    color: { scheme: "YlOrRd" },
    marks: [
      Plot.cell(data, {
        x: "x",
        y: "y",
        fill: "value",
        tip: true,
        inset: 0.5,
      }),
      Plot.text(data, {
        x: "x",
        y: "y",
        text: (d: { value: number }) =>
          typeof d.value === "number" ? d.value.toFixed(1) : String(d.value),
        fill: "white",
        fontSize: 10,
      }),
    ],
  };

  return <ObservablePlot options={options} title={title} />;
}
