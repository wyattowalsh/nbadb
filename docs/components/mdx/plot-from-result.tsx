"use client";

import { useCallback } from "react";
import * as Plot from "@observablehq/plot";
import {
  PlotMount,
  type PlotOptions,
  withDefaultPlotStyle,
} from "@/components/mdx/plot-mount";
import type { ChartInference } from "@/lib/chart-inference";

const PRIMARY = "var(--primary)";

/**
 * Renders an Observable Plot chart inferred from DuckDB query results.
 *
 * Accepts query rows plus a ChartInference object that describes the chart
 * type and axis mappings. Renders nothing when type is "none".
 */
export function PlotFromResult({
  rows,
  inference,
}: {
  rows: Record<string, unknown>[];
  inference: ChartInference;
}) {
  const createPlot = useCallback(() => {
    if (inference.type === "none" || rows.length === 0) return null;
    return buildPlot(rows, inference);
  }, [rows, inference]);

  if (inference.type === "none") return null;

  return (
    <div className="nba-viz-shell">
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">{inference.label}</p>
        </div>
      </div>
      <PlotMount createPlot={createPlot} className="overflow-x-auto px-2 py-3" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart builders
// ---------------------------------------------------------------------------

function buildPlot(
  rows: Record<string, unknown>[],
  inference: ChartInference,
): SVGSVGElement | HTMLElement | null {
  const { type, xColumn, yColumns } = inference;

  switch (type) {
    case "bar":
      return buildBar(rows, xColumn, yColumns[0]);
    case "line":
      return buildLine(rows, xColumn, yColumns[0]);
    case "scatter":
      return buildScatter(rows, xColumn, yColumns[0]);
    case "grouped-bar":
      return buildGroupedBar(rows, xColumn, yColumns);
    case "multi-line":
      return buildMultiLine(rows, xColumn, yColumns);
    default:
      return null;
  }
}

function createStyledPlot(options: PlotOptions) {
  return Plot.plot(withDefaultPlotStyle(options));
}

function buildBar(rows: Record<string, unknown>[], xCol: string, yCol: string) {
  return createStyledPlot({
    marginLeft: 120,
    x: { label: yCol, grid: true },
    y: { label: xCol },
    marks: [
      Plot.barX(rows, {
        x: yCol,
        y: xCol,
        sort: { y: "-x" },
        fill: PRIMARY,
        tip: true,
      }),
    ],
  });
}

function buildLine(
  rows: Record<string, unknown>[],
  xCol: string,
  yCol: string,
) {
  return createStyledPlot({
    x: { label: xCol },
    y: { label: yCol, grid: true },
    marks: [
      Plot.ruleY([0]),
      Plot.line(rows, {
        x: xCol,
        y: yCol,
        stroke: PRIMARY,
        strokeWidth: 2,
        tip: true,
      }),
    ],
  });
}

function buildScatter(
  rows: Record<string, unknown>[],
  xCol: string,
  yCol: string,
) {
  return createStyledPlot({
    x: { label: xCol },
    y: { label: yCol, grid: true },
    marks: [
      Plot.dot(rows, {
        x: xCol,
        y: yCol,
        fill: PRIMARY,
        fillOpacity: 0.6,
        r: 3,
        tip: true,
      }),
    ],
  });
}

function buildGroupedBar(
  rows: Record<string, unknown>[],
  xCol: string,
  yColumns: string[],
) {
  // Reshape: one entry per yColumn so we can use fill for grouping
  const reshaped = rows.flatMap((row) =>
    yColumns.map((yCol) => ({
      category: row[xCol],
      value: row[yCol] as number,
      series: yCol,
    })),
  );

  return createStyledPlot({
    x: { label: xCol },
    y: { label: null, grid: true },
    color: { legend: true },
    marks: [
      Plot.barY(reshaped, {
        x: "category",
        y: "value",
        fill: "series",
        tip: true,
      }),
    ],
  });
}

function buildMultiLine(
  rows: Record<string, unknown>[],
  xCol: string,
  yColumns: string[],
) {
  // Reshape: for each row, emit one entry per yColumn
  const reshaped = rows.flatMap((row) =>
    yColumns.map((yCol) => ({
      x: row[xCol],
      value: row[yCol] as number,
      series: yCol,
    })),
  );

  return createStyledPlot({
    x: { label: xCol },
    y: { label: null, grid: true },
    color: { legend: true },
    marks: [
      Plot.line(reshaped, {
        x: "x",
        y: "value",
        stroke: "series",
        tip: true,
      }),
    ],
  });
}
