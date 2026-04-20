import type { DocsContextRailMeta, GeneratedPageFrameMeta } from "./types";
import { getSectionMeta } from "./sections";

const defaultContextRailDescription =
  "Keep the mental model warm with adjacent pages, section hubs, and search-friendly routes into the same topic cluster.";

const docsAutogenCommand =
  "uv run nbadb docs-autogen --docs-root docs/content/docs";

type GeneratedPageContextRailOverrides = Partial<DocsContextRailMeta> &
  Pick<DocsContextRailMeta, "links" | "prompts">;

type GeneratedPageConfig = {
  frame?: GeneratedPageFrameMeta;
  contextRail?: GeneratedPageContextRailOverrides;
};

const generatedPageFrames: Record<string, GeneratedPageFrameMeta> = {
  "data-dictionary/raw": {
    eyebrow: "Generated field inventory",
    title: "Read the raw dictionary like a source manifest",
    description:
      "This page is exhaustive on purpose. Use it to confirm inbound field names, source result sets, and nullable behavior exactly as they landed before you switch to interpretation or warehouse-friendly naming.",
    stats: [
      {
        label: "Best for",
        value: "Source fidelity",
        note: "verify api-native names and payload shape without guessing",
      },
      {
        label: "Less useful for",
        value: "Join design",
        note: "raw names preserve upstream texture more than analyst ergonomics",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Start at the table heading",
        description:
          "Match the `raw_*` block to the endpoint family or result set you are tracing.",
      },
      {
        title: "Use the Source column as your replay marker",
        description:
          "The source path tells you which nba_api payload field produced each row in the inventory.",
      },
      {
        title: "Leave when the question becomes semantic",
        description:
          "If the name is exact but still not meaningful, switch to the glossary or field-reference page.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "Treat this as a generated lookup sheet for exactness. Curated pages explain meaning; this page proves what exists.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Use curated pages for interpretation, not inventory",
    modulesDescription:
      "Once you have found the exact raw field, these pages help you translate the term, decode the naming pattern, or reconnect the field to its source family.",
    modules: [
      {
        label: "Curated glossary",
        title: "Decode basketball metrics and abbreviations",
        href: "/docs/data-dictionary/glossary",
        description:
          "Best next stop when a field name is recognizable but the stat meaning is still fuzzy.",
      },
      {
        label: "Curated naming guide",
        title: "Read recurring field patterns faster",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Use the field guide to decode `_pct`, `_id`, flags, and common warehouse naming habits.",
      },
      {
        label: "Source scouting report",
        title: "Reconnect raw tables to endpoint families",
        href: "/docs/endpoints",
        description:
          "Jump back to extractor and result-set context when the real question is about the feed itself.",
      },
    ],
  },
  "data-dictionary/staging": {
    eyebrow: "Generated field inventory",
    title: "Read staging as the translation layer",
    description:
      "This inventory shows where raw payloads start sounding like a warehouse. Use it to verify normalized names, key cleanup, and source carry-through before you reason about downstream joins.",
    stats: [
      {
        label: "Best for",
        value: "Normalization checks",
        note: "confirm how raw fields were cleaned up for staging and load",
      },
      {
        label: "Best signal",
        value: "Join-ready keys",
        note: "staging names, foreign keys, and cleaned types usually get clearer here",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Compare staging names to the raw counterpart",
        description:
          "This is the right page when the upstream field exists, but you need the normalized warehouse-facing name.",
      },
      {
        title: "Watch the cleaned keys and types",
        description:
          "Staging is where foreign-key hints, renamed identifiers, and typed columns start becoming useful for SQL.",
      },
      {
        title: "Follow the possession downstream",
        description:
          "Once the staging shape is clear, switch to relationships or lineage to understand impact and joins.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "Use this page as the translation sheet between source payloads and the public warehouse. It is exhaustive by design, not editorial by design.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Turn cleaned field names into SQL decisions",
    modulesDescription:
      "These companion pages turn staging inventories into practical naming, join, and dependency guidance.",
    modules: [
      {
        label: "Curated naming guide",
        title: "Decode staging naming habits",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Use the naming guide when the cleaned column is clearer than raw, but still needs interpretation.",
      },
      {
        label: "Curated join guide",
        title: "Turn staging keys into relationship plans",
        href: "/docs/schema/relationships",
        description:
          "Move from renamed identifiers to the actual join lanes used in warehouse reads.",
      },
      {
        label: "Curated dependency replay",
        title: "Trace downstream tables before you change anything",
        href: "/docs/lineage/table-lineage",
        description:
          "Check impact radius when a staging field or table might feed multiple facts, dimensions, or aggregates.",
      },
    ],
  },
  "data-dictionary/star": {
    eyebrow: "Generated field inventory",
    title: "Treat the star dictionary as the public column inventory",
    description:
      "This is the exact field sheet for analyst-facing tables. Use it to verify public names, sources, and nullability, then switch to curated schema pages for grain, join strategy, and common usage.",
    stats: [
      {
        label: "Best for",
        value: "Public fields",
        note: "confirm the final warehouse columns analysts and dashboards actually touch",
      },
      {
        label: "Best clue",
        value: "Table family",
        note: "prefixes such as `dim_`, `fact_`, `bridge_`, and `analytics_` tell you how to read the block",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Identify the table family first",
        description:
          "Dimensions, facts, bridges, and analytics surfaces answer different questions even when some columns look similar.",
      },
      {
        title: "Use the Source column to check provenance",
        description:
          "Generated source paths are the fastest way to see whether a public field came straight from upstream or from a derived transform step.",
      },
      {
        title: "Switch back to curated schema pages for judgment",
        description:
          "This page tells you what exists. The curated schema pages tell you which public table is the smartest place to start.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "This page is the public field inventory, not the warehouse playbook. Pair it with curated table-family guidance when choosing a query path.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Choose the right public surface after you confirm the field",
    modulesDescription:
      "Use these curated pages to turn an exact field lookup into a table-family decision or a first working analysis.",
    modules: [
      {
        label: "Curated table family",
        title: "Start with dimensions when you need entity context",
        href: "/docs/schema/dimensions",
        description:
          "Use the dimension lineup card for identity, calendar, venue, and lookup surfaces.",
      },
      {
        label: "Curated table family",
        title: "Pick the smallest useful fact or bridge",
        href: "/docs/schema/facts",
        description:
          "Move from field inventory into grain-aware measurement families before you write a query.",
      },
      {
        label: "Curated workflow",
        title: "Turn the public surface into a first analysis",
        href: "/docs/guides/analytics-quickstart",
        description:
          "See the DuckDB-first analyst workflow that sits on top of these public columns.",
      },
    ],
  },
  "schema/raw-reference": {
    eyebrow: "Generated schema contract",
    title: "Use raw reference as the exact extraction contract",
    description:
      "This page is the source-of-truth contract for raw-tier schemas. It is the right place to verify upstream naming, constraints, and optionality before asking how the payload gets cleaned up downstream.",
    stats: [
      {
        label: "Best for",
        value: "Exact contracts",
        note: "confirm raw columns, nullability, and validation rules closest to extraction",
      },
      {
        label: "Naming mode",
        value: "API-shaped",
        note: "raw keeps upstream texture instead of warehouse-friendly semantics",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Go straight to the matching `raw_*` block",
        description:
          "These pages are dense, so start with the schema that matches the endpoint or result-set family you already have in mind.",
      },
      {
        title: "Read constraints and nullability before descriptions",
        description:
          "The biggest value here is exact contract behavior, especially when upstream payloads are inconsistent or optional.",
      },
      {
        title: "Leave when you need normalized names",
        description:
          "Once the source contract is clear, switch to staging reference or a curated schema page for warehouse-facing guidance.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "This page is for contract verification. It should feel dense because it is meant to answer exactness questions, not tell the whole story alone.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle:
      "Use curated docs when the contract is clear but the context is not",
    modulesDescription:
      "These pages help once you have confirmed the raw shape and need meaning, feed context, or pipeline placement.",
    modules: [
      {
        label: "Curated naming guide",
        title: "Decode raw column patterns quickly",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Translate suffixes, identifiers, and repeated field families that appear across raw contracts.",
      },
      {
        label: "Curated source context",
        title: "Reconnect schemas to endpoint families",
        href: "/docs/endpoints",
        description:
          "Use the endpoint scouting report when you need extractor and result-set context around a raw schema block.",
      },
      {
        label: "Curated system map",
        title: "See where raw sits in the pipeline",
        href: "/docs/diagrams/pipeline-flow",
        description:
          "Move from schema-level exactness into the broader extract → stage → transform flow.",
      },
    ],
  },
  "schema/staging-reference": {
    eyebrow: "Generated schema contract",
    title: "Use staging reference to verify cleanup before transforms",
    description:
      "This is the half-court contract: normalized columns, typed data, and load-ready keys before star-schema transforms begin. Use it to verify cleanup choices without reading transform code first.",
    stats: [
      {
        label: "Best for",
        value: "Cleanup verification",
        note: "confirm renamed fields, typing, and foreign-key hints in the warehouse-ready layer",
      },
      {
        label: "Best clue",
        value: "FK hints",
        note: "staging blocks often reveal the intended join anchors for downstream models",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Compare to the raw contract only when needed",
        description:
          "Staging is already cleaned up, so use raw reference only to answer what changed rather than rereading both pages in full.",
      },
      {
        title: "Focus on renamed identifiers and typed columns",
        description:
          "Those are usually the signals that matter most when you are planning joins or debugging transform assumptions.",
      },
      {
        title: "Follow dependencies once the shape is clear",
        description:
          "Switch to lineage or relationships when the next question is about impact radius or join strategy.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "Treat this page as the warehouse-ready contract layer. It explains exactly what staging guarantees, but not which final surface you should query next.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Turn staging contracts into join and dependency reasoning",
    modulesDescription:
      "These curated pages help once the cleanup is confirmed and the next question becomes how that staged data behaves downstream.",
    modules: [
      {
        label: "Curated join guide",
        title: "Translate cleaned keys into relationship lanes",
        href: "/docs/schema/relationships",
        description:
          "Use the join playbook when staging identifiers are clear and the next step is SQL shape.",
      },
      {
        label: "Curated dependency replay",
        title: "Trace which facts and dimensions inherit this stage",
        href: "/docs/lineage/table-lineage",
        description:
          "Best next stop when a staging change might ripple through multiple downstream outputs.",
      },
      {
        label: "Curated naming guide",
        title: "Decode warehouse-friendly field names",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Use the field guide when cleanup improved the name but not the full semantic picture.",
      },
    ],
  },
  "schema/star-reference": {
    eyebrow: "Generated schema contract",
    title: "Use star reference as the exact warehouse contract",
    description:
      "This is the scorebook for the public model. Use it to verify final columns, constraints, and foreign keys, then switch to curated schema pages when you need table selection, grain guidance, or join patterns.",
    stats: [
      {
        label: "Best for",
        value: "Final contracts",
        note: "verify the exact public schema that analysts, tests, and exports depend on",
      },
      {
        label: "Best clue",
        value: "Public grain",
        note: "the table name and constraint block tell you how to query without inventing columns",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Pick the public table family before reading columns",
        description:
          "Dimensions, facts, bridges, derived tables, and analytics views all surface different grains and workloads.",
      },
      {
        title: "Use constraints to keep joins honest",
        description:
          "Foreign keys and nullability often answer the real question faster than the descriptions alone.",
      },
      {
        title: "Switch to curated pages for judgment calls",
        description:
          "This page proves what exists; curated schema pages help you choose the right surface for the analysis.",
      },
    ],
    generatorLabel: "Schema metadata",
    ownershipNote:
      "Use this page as the contract surface of the final warehouse. It is exhaustive and exact, but intentionally not the whole onboarding story.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Turn exact public contracts into practical table choices",
    modulesDescription:
      "Once the star contract is confirmed, use curated pages to decide which table family or analyst shortcut fits the question.",
    modules: [
      {
        label: "Curated table family",
        title: "Use dimensions for stable entity context",
        href: "/docs/schema/dimensions",
        description:
          "Start here when the query needs player, team, season, date, or venue anchors.",
      },
      {
        label: "Curated table family",
        title: "Pick the right fact or bridge grain",
        href: "/docs/schema/facts",
        description:
          "Use the fact scouting report to avoid starting from a wider or noisier table than necessary.",
      },
      {
        label: "Curated shortcut",
        title: "Check whether an analytics view already solves it",
        href: "/docs/schema/analytics-views",
        description:
          "Look for a pre-joined outlet before rebuilding a common analyst surface by hand.",
      },
    ],
  },
  "diagrams/er-auto": {
    eyebrow: "Generated visual inventory",
    title: "Open the full ER board when the curated cut is not enough",
    description:
      "This diagram is exhaustive by design. Use it when you need the full schema-derived entity board, then step back to the curated ER diagram or schema guides when you need emphasis rather than total coverage.",
    stats: [
      {
        label: "Best for",
        value: "Full entity board",
        note: "see the entire schema-derived roster instead of the curated whiteboard cut",
      },
      {
        label: "Generated from",
        value: "Schema definitions",
        note: "the diagram stays source-derived so visual drift does not creep in",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from schema definitions instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Use it to confirm that a table or edge exists",
        description:
          "The auto board is strongest when the curated diagram feels too selective and you need the full inventory.",
      },
      {
        title: "Do not force conceptual reading from the dense view",
        description:
          "Once the existence check is done, jump back to the curated ER page for the faster mental model.",
      },
      {
        title: "Translate shapes into join plans elsewhere",
        description:
          "When the question becomes SQL rather than visualization, move to relationships or schema family docs.",
      },
    ],
    generatorLabel: "Schema definitions",
    ownershipNote:
      "This page is intentionally exhaustive and command-owned. Think of it as the full board, not the coach's highlighted cut.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Switch from the full board to the pages that add emphasis",
    modulesDescription:
      "These curated companions help once the exhaustive visual has answered the existence question and you need interpretation or SQL guidance.",
    modules: [
      {
        label: "Curated board",
        title: "Read the coach's-cut ER diagram",
        href: "/docs/diagrams/er-diagram",
        description:
          "Use the curated board when you want the fastest read on anchors, bridges, and model shape.",
      },
      {
        label: "Curated join guide",
        title: "Turn visual structure into relationship logic",
        href: "/docs/schema/relationships",
        description:
          "Move from boxes and edges into actual join lanes across the warehouse.",
      },
      {
        label: "Curated warehouse guide",
        title: "Drop into the schema family playbook",
        href: "/docs/schema",
        description:
          "Zoom from the exhaustive diagram into curated dimensions, facts, and analytics guidance.",
      },
    ],
  },
  "lineage/lineage-auto": {
    eyebrow: "Generated dependency map",
    title: "Use the generated lineage map for code-sourced coverage",
    description:
      "This page is the exhaustive replay pulled from code metadata. Use it when you need total dependency coverage, then switch to curated lineage pages when you want the possession slowed down and explained.",
    stats: [
      {
        label: "Best for",
        value: "Exhaustive lineage",
        note: "trace code-sourced upstream and downstream coverage without guessing",
      },
      {
        label: "Generated from",
        value: "Transform metadata",
        note: "keeps the dependency view aligned with transformer definitions",
      },
      {
        label: "Ownership",
        value: "Command-owned",
        note: "regenerate from lineage metadata instead of hand-editing",
      },
    ],
    steps: [
      {
        title: "Start with the table-level view for blast radius",
        description:
          "Use the top of the generated page to see whether a change affects one table or an entire downstream family.",
      },
      {
        title: "Use column lineage only when the problem is local",
        description:
          "If the breakage is one metric or key, the curated column-lineage page is the better explanatory cut.",
      },
      {
        title: "Reconnect the replay to source scouting when needed",
        description:
          "Once the dependency chain is known, jump upstream to endpoints if the real question is about the feed.",
      },
    ],
    generatorLabel: "Transformer metadata",
    ownershipNote:
      "This page is a generated replay map, not a narrated walkthrough. Pair it with curated lineage pages for explanation and examples.",
    regenerateCommand: docsAutogenCommand,
    modulesEyebrow: "Companion cuts",
    modulesTitle: "Switch from exhaustive replay to narrated debugging",
    modulesDescription:
      "These companion pages help you move from total coverage into the right debugging lens for the next question.",
    modules: [
      {
        label: "Curated replay",
        title: "Zoom out to full table movement",
        href: "/docs/lineage/table-lineage",
        description:
          "Use the table replay when you need to understand full upstream and downstream impact.",
      },
      {
        label: "Curated replay",
        title: "Slow the tape down to one field",
        href: "/docs/lineage/column-lineage",
        description:
          "Best next stop when the problem is a rename, foreign key, or single metric rather than a whole table.",
      },
      {
        label: "Source scouting report",
        title: "Reconnect the chain to the NBA API family",
        href: "/docs/endpoints",
        description:
          "Jump upstream when the dependency answer still needs extractor or result-set context.",
      },
    ],
  },
};

const generatedPageContextRailOverrides: Record<
  string,
  GeneratedPageContextRailOverrides
> = {
  "schema/raw-reference": {
    eyebrow: "Next possession",
    title: "From inbound feed to warehouse context",
    description:
      "Raw contracts tell you exactly what arrived from nba_api. These next stops explain how those source-native fields map to endpoint families, naming conventions, and pipeline stages.",
    links: [
      {
        title: "Field Reference",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Decode recurring suffixes, IDs, rates, and naming habits before scanning source-heavy column lists.",
      },
      {
        title: "Endpoints",
        href: "/docs/endpoints",
        description:
          "Reconnect raw schemas to the extractor families and result sets that produced them.",
      },
      {
        title: "Pipeline Flow",
        href: "/docs/diagrams/pipeline-flow",
        description:
          "See where raw capture sits between extraction, staging validation, and downstream transforms.",
      },
    ],
    prompts: [
      {
        label: "Source feed",
        query: "endpoints box scores raw schemas",
        description:
          "Start with the endpoint family when the raw block still feels too abstract.",
      },
      {
        label: "Naming decode",
        query: "field reference _pct _id raw naming",
        description:
          "Use this when the contract is exact but the semantics still need translation.",
      },
      {
        label: "Pipeline stage",
        query: "pipeline flow raw staging transform",
        description:
          "Follow the possession after extraction and before warehouse joins.",
      },
    ],
  },
  "schema/staging-reference": {
    eyebrow: "Next possession",
    title: "Translate staging cleanup into join intent",
    description:
      "Staging contracts show the half-court set: renamed columns, normalized types, and load-ready keys. Use these pages to move from cleanup details into joins, dependencies, and reader-facing naming.",
    links: [
      {
        title: "Relationships",
        href: "/docs/schema/relationships",
        description:
          "Turn normalized keys into concrete join lanes across player, team, game, and event analysis.",
      },
      {
        title: "Table Lineage",
        href: "/docs/lineage/table-lineage",
        description:
          "Trace which staging tables feed the downstream dimensions, facts, and aggregates you care about.",
      },
      {
        title: "Field Reference",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Use the naming guide when staging cleanup introduced warehouse-style field conventions.",
      },
    ],
    prompts: [
      {
        label: "Join lane",
        query: "schema relationships player_id team_id game_id",
        description:
          "Best next step when the question has shifted from cleanup to SQL shape.",
      },
      {
        label: "Downstream impact",
        query: "table lineage staging fact dimension",
        description:
          "Use lineage when a staging field change might ripple through multiple outputs.",
      },
      {
        label: "Normalization",
        query: "field reference staging snake_case naming",
        description:
          "Decode the warehouse-friendly naming that replaces API-native payload fields.",
      },
    ],
  },
  "schema/star-reference": {
    eyebrow: "Next possession",
    title: "Turn exact star contracts into working analysis",
    description:
      "The generated star reference is the scorebook. These curated pages help you decide which public tables to start with, how they join, and where analyst-friendly shortcuts already exist.",
    links: [
      {
        title: "Dimensions",
        href: "/docs/schema/dimensions",
        description:
          "Understand the identity and calendar tables that anchor most warehouse joins.",
      },
      {
        title: "Facts & Bridges",
        href: "/docs/schema/facts",
        description:
          "Choose the smallest useful fact family before you write a single query.",
      },
      {
        title: "Analytics Views",
        href: "/docs/schema/analytics-views",
        description:
          "Check whether a pre-joined analyst surface already answers the question faster.",
      },
    ],
    prompts: [
      {
        label: "Choose a grain",
        query: "fact_player_game grain facts bridges",
        description:
          "Use this when the star contract is clear but the right table family is not.",
      },
      {
        label: "Join cleanly",
        query: "schema relationships bridges joins",
        description:
          "Move from column inventory to safe join patterns without duplicating rows.",
      },
      {
        label: "Fast outlet",
        query: "analytics views player team complete",
        description:
          "Find analyst-friendly shortcuts before rebuilding common joins by hand.",
      },
    ],
  },
  "data-dictionary/raw": {
    eyebrow: "Next possession",
    title: "Decode source-native fields before you keep reading",
    description:
      "The raw dictionary is exhaustive by design. Use these pages to translate unfamiliar terms, connect fields back to source families, and understand where raw names fit in the pipeline.",
    links: [
      {
        title: "Glossary",
        href: "/docs/data-dictionary/glossary",
        description:
          "Decode basketball metrics, abbreviations, and common warehouse terms before reading dense inventories.",
      },
      {
        title: "Field Reference",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Learn the recurring column patterns that show up across raw, staging, and star layers.",
      },
      {
        title: "Endpoints",
        href: "/docs/endpoints",
        description:
          "Reconnect a raw column inventory to the nba_api families and result sets behind it.",
      },
    ],
    prompts: [
      {
        label: "Metric meaning",
        query: "glossary pie ts_pct usg_pct",
        description:
          "Best when the field name is familiar enough to recognize but not to trust.",
      },
      {
        label: "Naming pattern",
        query: "field reference raw naming conventions",
        description:
          "Use this to decode suffixes, IDs, and repeated schema habits quickly.",
      },
      {
        label: "Source family",
        query: "endpoints box score play by play tracking",
        description:
          "Jump to the source-side scouting report when you need feed context, not just fields.",
      },
    ],
  },
  "data-dictionary/staging": {
    eyebrow: "Next possession",
    title: "Use staging names as the translation layer",
    description:
      "Staging fields are where raw payloads start sounding like a warehouse. These next stops help you decode normalized names, trace upstream sources, and turn cleaned columns into join decisions.",
    links: [
      {
        title: "Field Reference",
        href: "/docs/data-dictionary/field-reference",
        description:
          "Translate staging naming habits into semantic meaning before reading transform code.",
      },
      {
        title: "Relationships",
        href: "/docs/schema/relationships",
        description:
          "Use the cleaned keys and renamed columns to plan safe star-schema joins.",
      },
      {
        title: "Table Lineage",
        href: "/docs/lineage/table-lineage",
        description:
          "Trace where a staging field comes from and which downstream outputs inherit it.",
      },
    ],
    prompts: [
      {
        label: "Normalization",
        query: "field reference staging snake_case",
        description:
          "Use this when a staging column reads cleaner than the raw name but still needs interpretation.",
      },
      {
        label: "Dependency path",
        query: "table lineage staging downstream facts",
        description:
          "Trace which final tables depend on a staging block before changing it.",
      },
      {
        label: "Join planning",
        query: "schema relationships game team player joins",
        description:
          "Turn cleaned keys into concrete query structure for warehouse reads.",
      },
    ],
  },
  "data-dictionary/star": {
    eyebrow: "Next possession",
    title: "Move from column meaning to analyst usage",
    description:
      "The star dictionary tells you what the public fields are. These next pages tell you which table families own them, how analysts usually join them, and where the fastest workflows already live.",
    links: [
      {
        title: "Dimensions",
        href: "/docs/schema/dimensions",
        description:
          "Start with the lineup card for identity, calendar, and lookup context.",
      },
      {
        title: "Facts & Bridges",
        href: "/docs/schema/facts",
        description:
          "Match the field inventory to the right measurement family and logical grain.",
      },
      {
        title: "Analytics Quickstart",
        href: "/docs/guides/analytics-quickstart",
        description:
          "See how the public surface turns into practical DuckDB-first analyst workflows.",
      },
    ],
    prompts: [
      {
        label: "Pick a table family",
        query: "dimensions facts bridges star schema",
        description:
          "Best when you know the fields but not which public surface should anchor the query.",
      },
      {
        label: "Join path",
        query: "schema relationships dim fact analytics",
        description:
          "Use curated join guidance before stitching the public model together by hand.",
      },
      {
        label: "First analysis",
        query: "analytics quickstart duckdb player game",
        description:
          "Take the field inventory straight into a concrete analyst workflow.",
      },
    ],
  },
  "diagrams/er-auto": {
    eyebrow: "Next possession",
    title: "Use the full board, then switch to the coach's cut",
    description:
      "The generated ER board is exhaustive. These curated pages help you turn that full inventory into the joins, table families, and model-level decisions you actually need next.",
    links: [
      {
        title: "ER Diagram",
        href: "/docs/diagrams/er-diagram",
        description:
          "Read the curated whiteboard version when you need emphasis, not every entity at once.",
      },
      {
        title: "Relationships",
        href: "/docs/schema/relationships",
        description:
          "Convert the shape of the board into concrete join lanes and grain decisions.",
      },
      {
        title: "Schema Reference",
        href: "/docs/schema",
        description:
          "Zoom from the full entity map into curated dimension, fact, and derived-table guidance.",
      },
    ],
    prompts: [
      {
        label: "Conceptual board",
        query: "ER diagram dim game dim player dim team",
        description:
          "Use the curated board when the full auto graph is too dense to parse quickly.",
      },
      {
        label: "Join planning",
        query: "schema relationships bridge tables",
        description:
          "Best next step after the visual shape is clear and SQL planning begins.",
      },
      {
        label: "Table families",
        query: "schema dimensions facts analytics views",
        description:
          "Move from entity inventory into the curated warehouse playbook.",
      },
    ],
  },
  "lineage/lineage-auto": {
    eyebrow: "Next possession",
    title: "Turn exhaustive lineage into practical debugging",
    description:
      "The generated lineage page gives you code-sourced coverage. These curated follow-ups help you replay the dependency chain at the table level, slow it down to a single field, or reconnect it to the source feed.",
    links: [
      {
        title: "Table Lineage",
        href: "/docs/lineage/table-lineage",
        description:
          "Trace full upstream and downstream table chains when a model or dashboard looks wrong.",
      },
      {
        title: "Column Lineage",
        href: "/docs/lineage/column-lineage",
        description:
          "Replay one field at a time when the issue is a rename, metric, or foreign key.",
      },
      {
        title: "Endpoints",
        href: "/docs/endpoints",
        description:
          "Reconnect the lineage chain to the nba_api source families that started the possession.",
      },
    ],
    prompts: [
      {
        label: "Full replay",
        query: "table lineage upstream downstream dependencies",
        description:
          "Use this when a change might affect an entire table family or dashboard.",
      },
      {
        label: "Single field",
        query: "column lineage player_id season_year fg_pct",
        description:
          "Best when the breakage is local to one column rather than the whole possession.",
      },
      {
        label: "Source scouting",
        query: "endpoints shot chart lineup play by play",
        description:
          "Jump upstream when the real question is about the feed, not the transform.",
      },
    ],
  },
};

function buildGeneratedPageConfigs(
  frames: Record<string, GeneratedPageFrameMeta>,
  contextRails: Record<string, GeneratedPageContextRailOverrides>,
): Record<string, GeneratedPageConfig> {
  const pageKeys = new Set([
    ...Object.keys(frames),
    ...Object.keys(contextRails),
  ]);
  const configs: Record<string, GeneratedPageConfig> = {};

  for (const pageKey of pageKeys) {
    configs[pageKey] = {
      frame: frames[pageKey],
      contextRail: contextRails[pageKey],
    };
  }

  return configs;
}

const generatedPageConfigs = buildGeneratedPageConfigs(
  generatedPageFrames,
  generatedPageContextRailOverrides,
);

export function getGeneratedPageConfig(
  slug?: string[],
): GeneratedPageConfig | null {
  const pageKey = slug?.join("/") ?? "";
  return generatedPageConfigs[pageKey] ?? null;
}

export function getDocsContextRail(slug?: string[]): DocsContextRailMeta {
  const section = getSectionMeta(slug);
  const customRail = getGeneratedPageConfig(slug)?.contextRail;

  return {
    eyebrow: customRail?.eyebrow ?? "Keep moving",
    title: customRail?.title ?? "Stay in the same possession",
    description: customRail?.description ?? defaultContextRailDescription,
    hubHref: customRail?.hubHref ?? section.hubHref,
    hubLabel: customRail?.hubLabel ?? "Section hub",
    links: customRail?.links ?? section.quickLinks,
    prompts: customRail?.prompts ?? section.prompts,
  };
}

export function getGeneratedPageFrame(
  slug?: string[],
): GeneratedPageFrameMeta | null {
  return getGeneratedPageConfig(slug)?.frame ?? null;
}
