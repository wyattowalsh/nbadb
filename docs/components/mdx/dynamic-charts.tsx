"use client";

import dynamic from "next/dynamic";

export const ObservablePlot = dynamic(
  () => import("./observable-plot").then((m) => m.ObservablePlot),
  { ssr: false },
);
export const ShotChart = dynamic(
  () => import("./observable-plot").then((m) => m.ShotChart),
  { ssr: false },
);
export const GameFlow = dynamic(
  () => import("./observable-plot").then((m) => m.GameFlow),
  { ssr: false },
);
export const PlayerCompare = dynamic(
  () => import("./observable-plot").then((m) => m.PlayerCompare),
  { ssr: false },
);
export const SeasonTrend = dynamic(
  () => import("./observable-plot").then((m) => m.SeasonTrend),
  { ssr: false },
);
export const DistributionPlot = dynamic(
  () => import("./observable-plot").then((m) => m.DistributionPlot),
  { ssr: false },
);
export const HeatmapGrid = dynamic(
  () => import("./observable-plot").then((m) => m.HeatmapGrid),
  { ssr: false },
);
export const SchemaExplorer = dynamic(
  () => import("./schema-explorer").then((m) => m.SchemaExplorer),
  { ssr: false },
);
export const LineageExplorer = dynamic(
  () => import("./lineage-explorer").then((m) => m.LineageExplorer),
  { ssr: false },
);
