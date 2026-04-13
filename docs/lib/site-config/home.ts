import type { AudienceLane, HeroSignal, SearchPrompt } from "./types";

export const heroSignals: HeroSignal[] = [
  {
    label: "Warehouse",
    title: "Star-schema depth",
    description:
      "Dimensions, facts, bridges, and derived views packaged like a scouting department data room.",
  },
  {
    label: "Coverage",
    title: "League-wide endpoint reach",
    description:
      "Box scores, play-by-play, draft, standings, shot charts, synergy, and more in one reference system.",
  },
  {
    label: "Film room",
    title: "Readable analysis paths",
    description:
      "Guides, diagrams, and lineage pages that explain how raw feeds become analyst-ready tables.",
  },
];

export const searchPrompts: SearchPrompt[] = [
  {
    label: "Find a table",
    query: "fact_player_game",
    description: "Jump directly to the warehouse grain analysts touch most.",
  },
  {
    label: "Trace a process",
    query: "pipeline flow staging transform export",
    description: "Use diagrams and lineage pages as a possession map.",
  },
  {
    label: "Scout coverage",
    query: "draft endpoints shot chart lineup",
    description:
      "Discover endpoint families without already knowing the docs tree.",
  },
];

export const audienceLanes: AudienceLane[] = [
  {
    label: "Analyst",
    title: "Get from schema to SQL fast",
    href: "/docs/guides/analytics-quickstart",
    description:
      "Use the warehouse map, then drop straight into DuckDB recipes and comparison workflows.",
  },
  {
    label: "Operator",
    title: "Run daily updates with fewer surprises",
    href: "/docs/guides/daily-updates",
    description:
      "Treat the pipeline like a gameday checklist with status, quality, and recovery guidance.",
  },
  {
    label: "Explorer",
    title: "Try live DuckDB in the browser",
    href: "/docs/playground",
    description:
      "Warm up with DuckDB-WASM, self-contained NBA-flavored sample queries, and a no-install route into the docs.",
  },
];
