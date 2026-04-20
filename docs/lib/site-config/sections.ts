import type { SectionId, SectionMeta } from "./types";

const sectionMeta: Record<SectionId, SectionMeta> = {
  core: {
    id: "core",
    label: "Core Docs",
    eyebrow: "Jump Ball",
    cue: "Arena Map",
    blurb:
      "Start here for setup, architecture, command references, and the fastest route into the warehouse.",
    hubHref: "/docs",
    stats: [
      { label: "Entry Pages", value: "4" },
      { label: "Sections", value: "7" },
      { label: "Search Lanes", value: "3" },
    ],
    quickLinks: [
      {
        title: "Installation",
        href: "/docs/installation",
        description:
          "Get the project running locally and understand the tooling footprint.",
      },
      {
        title: "Architecture",
        href: "/docs/architecture",
        description:
          "Follow the full extract → load → transform → export pipeline.",
      },
      {
        title: "CLI Reference",
        href: "/docs/cli-reference",
        description: "Jump straight to commands and operational entry points.",
      },
    ],
    prompts: [
      {
        label: "Search",
        query: "installation architecture cli reference",
        description: "The fastest way to locate the docs front door surfaces.",
      },
      {
        label: "Start here",
        query: "role based onboarding analytics quickstart",
        description: "Best jump for a new analyst or operator.",
      },
      {
        label: "Orient",
        query: "architecture pipeline flow",
        description: "Build the mental model before reading table detail.",
      },
    ],
  },
  schema: {
    id: "schema",
    label: "Schema Reference",
    eyebrow: "Court Geometry",
    cue: "Half-Court Map",
    blurb:
      "Trace the warehouse shape: dimensions, facts, derived tables, analytics views, and structural relationships.",
    hubHref: "/docs/schema",
    stats: [
      { label: "Layers", value: "5" },
      { label: "Surface", value: "dims · facts · aggs" },
      { label: "Best For", value: "Table selection" },
    ],
    quickLinks: [
      {
        title: "Dimensions",
        href: "/docs/schema/dimensions",
        description:
          "Player, team, and calendar structure with SCD notes where it matters.",
      },
      {
        title: "Facts",
        href: "/docs/schema/facts",
        description:
          "Grain, measures, and event-heavy tables that drive analytics workflows.",
      },
      {
        title: "Relationships",
        href: "/docs/schema/relationships",
        description:
          "See how dimensions, facts, and bridges connect across the model.",
      },
    ],
    prompts: [
      {
        label: "Primary grain",
        query: "fact_player_game grain",
        description: "Start with the table most analysts need first.",
      },
      {
        label: "Join logic",
        query: "schema relationships bridges",
        description: "Understand how warehouse edges connect.",
      },
      {
        label: "Derived layer",
        query: "analytics views derived tables",
        description: "Find rollups and consumer-friendly surfaces fast.",
      },
    ],
  },
  "data-dictionary": {
    id: "data-dictionary",
    label: "Data Dictionary",
    eyebrow: "Stat Legend",
    cue: "Scoreboard Key",
    blurb:
      "Look up field meaning across raw, staging, and star layers with clearer naming and semantic framing.",
    hubHref: "/docs/data-dictionary",
    stats: [
      { label: "Reference Tiers", value: "3" },
      { label: "Lookup Views", value: "6" },
      { label: "Reader Modes", value: "Field · Glossary" },
    ],
    quickLinks: [
      {
        title: "Glossary",
        href: "/docs/data-dictionary/glossary",
        description: "Decode the core warehouse and basketball terminology.",
      },
      {
        title: "Field Reference",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Find fields faster with better semantics and scanning cues.",
      },
      {
        title: "Star Dictionary",
        href: "/docs/data-dictionary/star",
        description: "Focus on the consumer-facing fields analysts touch most.",
      },
    ],
    prompts: [
      {
        label: "Naming",
        query: "glossary staging star field meanings",
        description: "Decode a column before you use it in production.",
      },
      {
        label: "Business meaning",
        query: "field reference possessions pace efficiency",
        description: "Pair warehouse terms with basketball semantics.",
      },
      {
        label: "Consumer view",
        query: "star dictionary player team",
        description: "Stay in the analyst-facing layer.",
      },
    ],
  },
  diagrams: {
    id: "diagrams",
    label: "Diagrams",
    eyebrow: "Playbook Board",
    cue: "Telestrator",
    blurb:
      "Visualize ER structure, pipeline flow, and endpoint coverage like a coach’s board layered over warehouse detail.",
    hubHref: "/docs/diagrams",
    stats: [
      { label: "Diagram Pages", value: "5" },
      { label: "Auto-Generated", value: "2" },
      { label: "Best Use", value: "Orientation" },
    ],
    quickLinks: [
      {
        title: "ER Diagram",
        href: "/docs/diagrams/er-diagram",
        description:
          "Read the conceptual entity map before dropping into table-level detail.",
      },
      {
        title: "Pipeline Flow",
        href: "/docs/diagrams/pipeline-flow",
        description: "Follow orchestration states from extraction to export.",
      },
      {
        title: "Endpoint Map",
        href: "/docs/diagrams/endpoint-map",
        description:
          "See coverage by endpoint family and extraction responsibility.",
      },
    ],
    prompts: [
      {
        label: "System map",
        query: "ER diagram relationships",
        description: "Use visuals to understand structure before prose.",
      },
      {
        label: "Pipeline path",
        query: "pipeline flow checkpoints export",
        description: "Follow how data moves through the possession.",
      },
      {
        label: "Coverage map",
        query: "endpoint map box score draft lineup",
        description: "Scan the breadth of extractor coverage at a glance.",
      },
    ],
  },
  endpoints: {
    id: "endpoints",
    label: "Endpoints",
    eyebrow: "Coverage Board",
    cue: "Scouting Report",
    blurb:
      "Browse extractor families with stronger route cues, better grouping, and more basketball-native framing.",
    hubHref: "/docs/endpoints",
    stats: [
      { label: "Coverage", value: "Full league" },
      { label: "Scope", value: "stats.nba.com" },
      { label: "Best For", value: "Feed discovery" },
    ],
    quickLinks: [
      {
        title: "Box Scores",
        href: "/docs/endpoints/box-scores",
        description: "Jump into the core game-by-game statistical feeds.",
      },
      {
        title: "Play-by-Play",
        href: "/docs/endpoints/play-by-play",
        description:
          "Understand event sequencing, possessions, and timeline-heavy feeds.",
      },
      {
        title: "Draft",
        href: "/docs/endpoints/draft",
        description:
          "See how prospect-facing feeds fit into the broader extractor surface.",
      },
    ],
    prompts: [
      {
        label: "Game feeds",
        query: "box score play by play scoreboard",
        description: "Start with high-leverage live-game coverage surfaces.",
      },
      {
        label: "Tracking",
        query: "shot chart synergy lineup tracking",
        description: "Find richer context feeds for analyst workflows.",
      },
      {
        label: "Seasonal",
        query: "draft standings awards history",
        description: "Explore slower-changing league and prospect surfaces.",
      },
    ],
  },
  lineage: {
    id: "lineage",
    label: "Lineage",
    eyebrow: "Ball Movement",
    cue: "Possession Chain",
    blurb:
      "Track how tables and columns move through the pipeline with clearer ancestry, dependency, and handoff surfaces.",
    hubHref: "/docs/lineage",
    stats: [
      { label: "Lineage Views", value: "4" },
      { label: "Transform Paths", value: "100+" },
      { label: "Best For", value: "Debugging" },
    ],
    quickLinks: [
      {
        title: "Table Lineage",
        href: "/docs/lineage/table-lineage",
        description:
          "Trace upstream and downstream table dependencies across transforms.",
      },
      {
        title: "Column Lineage",
        href: "/docs/lineage/column-lineage",
        description: "Follow field-level ancestry and derived expression flow.",
      },
      {
        title: "Auto Lineage",
        href: "/docs/lineage/lineage-auto",
        description:
          "Browse generated lineage output with stronger reading guidance.",
      },
    ],
    prompts: [
      {
        label: "Upstream",
        query: "table lineage upstream dependencies",
        description: "Find what feeds a table before changing anything.",
      },
      {
        label: "Column ancestry",
        query: "column lineage derived expressions",
        description: "Debug field semantics without guessing.",
      },
      {
        label: "Recovery",
        query: "transform checkpoints lineage",
        description: "Pair lineage views with operational reasoning.",
      },
    ],
  },
  guides: {
    id: "guides",
    label: "Guides",
    eyebrow: "Playbook",
    cue: "Set Menu",
    blurb:
      "Hands-on workflows for analysts and operators, with stronger progression cues and basketball-informed framing.",
    hubHref: "/docs/guides",
    stats: [
      { label: "Guides", value: "11" },
      { label: "User Paths", value: "Ops · Analysis" },
      { label: "Best Use", value: "Execution" },
    ],
    quickLinks: [
      {
        title: "Analytics Quickstart",
        href: "/docs/guides/analytics-quickstart",
        description:
          "Land quick wins fast and move from setup to analysis with intent.",
      },
      {
        title: "SQL Playground",
        href: "/docs/playground",
        description:
          "Rehearse DuckDB syntax and query structure in the browser before touching the full warehouse.",
      },
      {
        title: "DuckDB Query Examples",
        href: "/docs/guides/duckdb-queries",
        description:
          "Move from the browser sandbox into real warehouse query patterns and analyst-ready examples.",
      },
    ],
    prompts: [
      {
        label: "Quick wins",
        query: "analytics quickstart sql playground duckdb queries",
        description: "Best path for a first working analysis.",
      },
      {
        label: "Browser sandbox",
        query: "sql playground duckdb wasm browser",
        description: "Use when you want a live no-install SQL drill first.",
      },
      {
        label: "Operations",
        query: "daily updates troubleshooting playbook",
        description: "Use when you are on the hook for a healthy pipeline.",
      },
    ],
  },
};

const sectionOrder: SectionId[] = [
  "schema",
  "endpoints",
  "lineage",
  "guides",
  "diagrams",
  "data-dictionary",
];

export const docsSections = sectionOrder.map((id) => sectionMeta[id]);

const docsNavSectionOrder: SectionId[] = [
  "core",
  "schema",
  "endpoints",
  "lineage",
  "diagrams",
  "guides",
];

export const docsNavLinks = [
  ...docsNavSectionOrder.map((id) => {
    const section = sectionMeta[id];

    return {
      text: id === "core" ? "Docs" : section.label,
      url: section.hubHref,
      active: "nested-url" as const,
      on: "nav" as const,
    };
  }),
  {
    type: "button" as const,
    text: "Kaggle",
    url: "https://www.kaggle.com/datasets/wyattowalsh/basketball",
    external: true,
    on: "nav" as const,
  },
];

export function getSectionId(slug?: string[]): SectionId {
  const top = slug?.[0];

  switch (top) {
    case "schema":
      return "schema";
    case "data-dictionary":
      return "data-dictionary";
    case "diagrams":
      return "diagrams";
    case "endpoints":
      return "endpoints";
    case "lineage":
      return "lineage";
    case "guides":
      return "guides";
    default:
      return "core";
  }
}

export function getSectionMeta(slug?: string[]): SectionMeta {
  return sectionMeta[getSectionId(slug)];
}
