"use client";

import { Component, type ReactNode } from "react";
import dynamic from "next/dynamic";

/* ── Shared loading placeholder ─────────────────────── */

function VizShellPlaceholder({ message }: { message: string }) {
  return (
    <div
      className="nba-viz-shell flex items-center justify-center"
      style={{ minHeight: "16rem" }}
    >
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

/* ── Error boundary for heavy interactive widgets ───── */

interface WidgetErrorBoundaryProps {
  name: string;
  children: ReactNode;
}

interface WidgetErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class WidgetErrorBoundary extends Component<
  WidgetErrorBoundaryProps,
  WidgetErrorBoundaryState
> {
  constructor(props: WidgetErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): WidgetErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="nba-viz-shell flex flex-col items-center justify-center gap-2"
          style={{ minHeight: "10rem" }}
        >
          <p className="text-sm font-medium text-destructive">
            {this.props.name} failed to load
          </p>
          <p className="text-xs text-muted-foreground">
            {this.state.error?.message ?? "An unexpected error occurred."}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-2 rounded-[var(--radius-md)] border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * Wrap a dynamic component with an error boundary that shows a friendly
 * fallback inside an `.nba-viz-shell` container.
 */
function withErrorBoundary<T extends object>(
  name: string,
  Comp: React.ComponentType<T>,
) {
  return function BoundedComponent(props: T) {
    return (
      <WidgetErrorBoundary name={name}>
        <Comp {...props} />
      </WidgetErrorBoundary>
    );
  };
}

export const ObservablePlot = withErrorBoundary(
  "Observable Plot",
  dynamic(() => import("./observable-plot").then((m) => m.ObservablePlot), { ssr: false }),
);
export const ShotChart = withErrorBoundary(
  "Shot Chart",
  dynamic(() => import("./observable-plot").then((m) => m.ShotChart), { ssr: false }),
);
export const GameFlow = withErrorBoundary(
  "Game Flow",
  dynamic(() => import("./observable-plot").then((m) => m.GameFlow), { ssr: false }),
);
export const PlayerCompare = withErrorBoundary(
  "Player Compare",
  dynamic(() => import("./observable-plot").then((m) => m.PlayerCompare), { ssr: false }),
);
export const SeasonTrend = withErrorBoundary(
  "Season Trend",
  dynamic(() => import("./observable-plot").then((m) => m.SeasonTrend), { ssr: false }),
);
export const DistributionPlot = withErrorBoundary(
  "Distribution Plot",
  dynamic(() => import("./observable-plot").then((m) => m.DistributionPlot), { ssr: false }),
);
export const HeatmapGrid = withErrorBoundary(
  "Heatmap Grid",
  dynamic(() => import("./observable-plot").then((m) => m.HeatmapGrid), { ssr: false }),
);
/* ── Heavy interactive components (lazy + error-bounded) ── */

const _SchemaExplorer = dynamic(
  () => import("./schema-explorer").then((m) => m.SchemaExplorer),
  {
    ssr: false,
    loading: () => (
      <VizShellPlaceholder message="Loading schema explorer\u2026" />
    ),
  },
);
export const SchemaExplorer = withErrorBoundary(
  "Schema Explorer",
  _SchemaExplorer,
);

const _LineageExplorer = dynamic(
  () => import("./lineage-explorer").then((m) => m.LineageExplorer),
  {
    ssr: false,
    loading: () => (
      <VizShellPlaceholder message="Loading lineage explorer\u2026" />
    ),
  },
);
export const LineageExplorer = withErrorBoundary(
  "Lineage Explorer",
  _LineageExplorer,
);

const _SqlPlayground = dynamic(
  () => import("./sql-playground").then((m) => m.SqlPlayground),
  {
    ssr: false,
    loading: () => (
      <VizShellPlaceholder message="Loading SQL playground\u2026" />
    ),
  },
);
export const SqlPlayground = withErrorBoundary(
  "SQL Playground",
  _SqlPlayground,
);
