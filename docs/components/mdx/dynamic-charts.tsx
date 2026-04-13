"use client";

import {
  Component,
  type ComponentType,
  type ReactNode,
  type JSX,
} from "react";
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

function createDynamicWidget<T extends object>(
  name: string,
  load: () => Promise<ComponentType<T>>,
  loadingMessage?: string,
) {
  const Comp = dynamic(load, {
    ssr: false,
    ...(loadingMessage
      ? {
          loading: (): JSX.Element => (
            <VizShellPlaceholder message={loadingMessage} />
          ),
        }
      : {}),
  });

  return withErrorBoundary(name, Comp);
}

const loadObservablePlotModule = () => import("./observable-plot");

export const ObservablePlot = createDynamicWidget(
  "Observable Plot",
  () => loadObservablePlotModule().then((module) => module.ObservablePlot),
);
export const ShotChart = createDynamicWidget(
  "Shot Chart",
  () => loadObservablePlotModule().then((module) => module.ShotChart),
);
export const GameFlow = createDynamicWidget(
  "Game Flow",
  () => loadObservablePlotModule().then((module) => module.GameFlow),
);
export const PlayerCompare = createDynamicWidget(
  "Player Compare",
  () => loadObservablePlotModule().then((module) => module.PlayerCompare),
);
export const SeasonTrend = createDynamicWidget(
  "Season Trend",
  () => loadObservablePlotModule().then((module) => module.SeasonTrend),
);
export const DistributionPlot = createDynamicWidget(
  "Distribution Plot",
  () => loadObservablePlotModule().then((module) => module.DistributionPlot),
);
export const HeatmapGrid = createDynamicWidget(
  "Heatmap Grid",
  () => loadObservablePlotModule().then((module) => module.HeatmapGrid),
);
/* ── Heavy interactive components (lazy + error-bounded) ── */

export const SchemaExplorer = createDynamicWidget(
  "Schema Explorer",
  () => import("./schema-explorer").then((module) => module.SchemaExplorer),
  "Loading schema explorer\u2026",
);

export const LineageExplorer = createDynamicWidget(
  "Lineage Explorer",
  () => import("./lineage-explorer").then((module) => module.LineageExplorer),
  "Loading lineage explorer\u2026",
);

export const SqlPlayground = createDynamicWidget(
  "SQL Playground",
  () => import("./sql-playground").then((module) => module.SqlPlayground),
  "Loading SQL playground\u2026",
);
