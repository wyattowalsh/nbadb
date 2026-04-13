import Link from "next/link";
import type { TOCItemType } from "fumadocs-core/toc";
import { ArrowRight, Blocks, Command, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import schemaCoverage from "@/lib/generated/schema-coverage.json";
import {
  getGeneratedSourceGroupKey,
  getGeneratedStarGroupKey,
  getGeneratedStarGroupLabel,
  groupGeneratedItems,
  humanizeGeneratedIdentifier,
  sortGeneratedSourceGroups,
  sortGeneratedStarGroups,
} from "@/lib/generated-grouping";
import { getGeneratedPageFrame } from "@/lib/site-config";

export function DocsGeneratedEntrySurface({ slug }: { slug?: string[] }) {
  const frame = getGeneratedPageFrame(slug);

  if (!frame) {
    return null;
  }

  return (
    <section className="mt-8 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="border border-border bg-card p-4 md:p-5">
        <div className="flex flex-wrap gap-2">
          <Badge variant="primary">Generated page</Badge>
          <Badge variant="default">Command-owned</Badge>
          <Badge variant="muted">{frame.generatorLabel}</Badge>
        </div>

        <div className="mt-4 space-y-3">
          <p className="nba-kicker">{frame.eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {frame.title}
          </h2>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
            {frame.description}
          </p>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {frame.stats.map((stat) => (
            <div
              key={stat.label}
              className="border border-border bg-muted px-3 py-2"
            >
              <div className="nba-metric-label">{stat.label}</div>
              <div className="nba-scoreboard-value mt-1 text-xl text-foreground">
                {stat.value}
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {stat.note}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-6">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            <Search className="size-3.5 text-primary" />
            How to work this page
          </div>
          <div className="mt-3 rounded-2xl border border-border bg-muted/60 p-3 md:p-4">
            <div className="grid gap-3 md:grid-cols-3">
              {frame.steps.map((step, index) => (
                <div
                  key={step.title}
                  className="rounded-xl border border-border/80 bg-background/80 px-3 py-3"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-primary/25 bg-primary/12 text-xs font-semibold text-primary">
                      {index + 1}
                    </span>
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-foreground">
                        {step.title}
                      </h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {step.description}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <aside className="border border-border bg-card p-4 md:p-5">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-foreground">
          <Command className="size-3.5 text-primary" />
          Generator boundary
        </div>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {frame.ownershipNote}
        </p>
        <div className="mt-4 border border-border bg-muted p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Regenerate with
          </div>
          <code className="mt-2 block overflow-x-auto font-mono text-[0.78rem] leading-6 text-foreground">
            {frame.regenerateCommand}
          </code>
        </div>
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          If the content drifts from code, refresh the generator instead of
          hand-editing the artifact.
        </p>
      </aside>
    </section>
  );
}

type SchemaCoverageSurfaceMeta = {
  eyebrow: string;
  title: string;
  description: string;
};

const schemaCoverageSurfaceMeta: Record<string, SchemaCoverageSurfaceMeta> = {
  schema: {
    eyebrow: "Coverage boundary",
    title:
      "Schema-backed reference coverage is narrower than total lineage coverage",
    description:
      "The generated schema reference layer is intentionally exact, but it does not cover every transform output yet. Use this summary to see what the contract layer currently includes before you assume an output has a schema-backed final-tier reference.",
  },
  "schema/star-reference": {
    eyebrow: "Coverage boundary",
    title:
      "This contract page covers only outputs with generated schema entries",
    description:
      "The star reference is the exact contract layer for outputs that currently have generated schema metadata. Some lineage-tracked outputs still sit outside this reference layer, so absence here is a coverage limit, not proof that an output does not exist.",
  },
  "lineage/lineage-auto": {
    eyebrow: "Coverage boundary",
    title: "Lineage coverage is broader than schema-reference coverage",
    description:
      "This page can list more outputs than the generated schema reference pages because lineage is sourced from transform metadata. The gap below is the current set of outputs that still lack a generated schema-backed contract entry.",
  },
};

function formatCoveragePercent(value: number) {
  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(value)}%`;
}

export function DocsSchemaCoverageSurface({ slug }: { slug?: string[] }) {
  const pageKey = slug?.join("/") ?? "";
  const meta = schemaCoverageSurfaceMeta[pageKey];

  if (!meta) {
    return null;
  }

  const coveredOutputs = schemaCoverage.schema_table_count;
  const totalOutputs = schemaCoverage.lineage_output_count;
  const uncoveredOutputs = schemaCoverage.missing_schema_output_count;
  const coveragePercent =
    totalOutputs === 0 ? 0 : (coveredOutputs / totalOutputs) * 100;
  const exampleOutputs = schemaCoverage.missing_schema_outputs.slice(0, 3);
  const remainingExampleCount = Math.max(
    uncoveredOutputs - exampleOutputs.length,
    0,
  );

  return (
    <section className="mt-8 border border-border bg-card p-4 md:p-5">
      <div className="flex flex-wrap gap-2">
        <Badge variant="primary">Coverage boundary</Badge>
        <Badge variant="default">
          {coveredOutputs} / {totalOutputs} outputs
        </Badge>
        <Badge variant="muted">
          {formatCoveragePercent(coveragePercent)} schema-backed
        </Badge>
      </div>

      <div className="mt-4 space-y-3">
        <p className="nba-kicker">{meta.eyebrow}</p>
        <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          {meta.title}
        </h2>
        <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
          {meta.description}
        </p>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            What coverage means
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            An output counts as covered only when <code>docs-autogen</code> can
            pair a lineage-tracked output with a generated schema reference
            entry.
          </p>
        </div>
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            What it does not mean
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            The remaining {uncoveredOutputs} outputs may still appear in lineage
            or curated docs, but they do not yet have this schema-backed
            contract layer.
          </p>
        </div>
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Verify current numbers
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Source of truth:{" "}
            <code>docs/lib/generated/schema-coverage.json</code>. Refresh it
            with{" "}
            <code>uv run nbadb docs-autogen --docs-root docs/content/docs</code>
            .
          </p>
        </div>
      </div>

      {exampleOutputs.length > 0 ? (
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          Current examples outside this layer:{" "}
          {exampleOutputs.map((output, index) => (
            <span key={output}>
              <code>{output}</code>
              {index < exampleOutputs.length - 1 ? ", " : ""}
            </span>
          ))}
          {remainingExampleCount > 0
            ? `, and ${remainingExampleCount} more.`
            : "."}
        </p>
      ) : null}
    </section>
  );
}

type GeneratedScanSurfaceMeta = {
  eyebrow: string;
  title: string;
  description: string;
  groupingLabel: string;
  itemLabel: string;
  sourceLabel?: string;
};

type GeneratedScanCluster = {
  key: string;
  label: string;
  description: string;
  items: Array<{ title: string; url: string }>;
};

const generatedScanSurfaceMeta: Record<string, GeneratedScanSurfaceMeta> = {
  "data-dictionary/raw": {
    eyebrow: "Quick scan",
    title: "Jump by source family before reading row by row",
    description:
      "Use these anchor clusters to land on the right raw table block fast, then read the exact field inventory only where it matters.",
    groupingLabel: "Source families",
    itemLabel: "table blocks",
  },
  "data-dictionary/staging": {
    eyebrow: "Quick scan",
    title: "Jump by cleaned staging family",
    description:
      "Scan the normalized table groups first so you do not have to read the full staging inventory top to bottom.",
    groupingLabel: "Staging families",
    itemLabel: "table blocks",
  },
  "data-dictionary/star": {
    eyebrow: "Quick scan",
    title: "Start with the public table family, then drill into columns",
    description:
      "The fastest read is to choose the right public surface first, then use the generated dictionary as the exact field sheet for that family.",
    groupingLabel: "Public families",
    itemLabel: "table blocks",
  },
  "diagrams/er-auto": {
    eyebrow: "Quick scan",
    title: "Use the full ER board as an existence check, not a lecture",
    description:
      "The auto ER diagram is strongest when you need to confirm that a table or relationship exists. Use these routes to leave the exhaustive board quickly once the answer is visible.",
    groupingLabel: "Reading lanes",
    itemLabel: "jump routes",
    sourceLabel: "Route-guided",
  },
  "lineage/lineage-auto": {
    eyebrow: "Quick scan",
    title: "Read the generated replay in the right order",
    description:
      "Start with blast radius, then slow the tape down to one field only when the problem is truly local. These routes keep the exhaustive map readable.",
    groupingLabel: "Replay lanes",
    itemLabel: "jump routes",
    sourceLabel: "Route-guided",
  },
  "schema/raw-reference": {
    eyebrow: "Quick scan",
    title: "Find the source contract you actually need",
    description:
      "These contract pages scan best when you jump straight to the matching raw family instead of reading every schema in order.",
    groupingLabel: "Source families",
    itemLabel: "schema blocks",
  },
  "schema/staging-reference": {
    eyebrow: "Quick scan",
    title: "Group staging contracts by cleanup lane",
    description:
      "Use the clustered anchors to find the normalized staging block first, then read constraints and nullability in context.",
    groupingLabel: "Staging families",
    itemLabel: "schema blocks",
  },
  "schema/star-reference": {
    eyebrow: "Quick scan",
    title: "Choose the warehouse family before reading the contract",
    description:
      "Dimensions, facts, bridges, rollups, and analytics views answer different questions. Start there, then read the exact schema block.",
    groupingLabel: "Public families",
    itemLabel: "schema blocks",
  },
};

const generatedManualScanClusters: Record<string, GeneratedScanCluster[]> = {
  "diagrams/er-auto": [
    {
      key: "existence-check",
      label: "Confirm the board exists",
      description:
        "Use the exhaustive ER diagram to verify that a table, bridge, or edge is present before moving back to a more narrated page.",
      items: [
        { title: "Coach's-cut ER diagram", url: "/docs/diagrams/er-diagram" },
        { title: "Schema Reference", url: "/docs/schema" },
        { title: "Relationships", url: "/docs/schema/relationships" },
      ],
    },
    {
      key: "best-next-cut",
      label: "Leave with the right next question",
      description:
        "Once the existence check is done, switch to the curated page that best matches the next decision: shape, joins, or table-family choice.",
      items: [
        { title: "Dimensions", url: "/docs/schema/dimensions" },
        { title: "Facts", url: "/docs/schema/facts" },
        { title: "Analytics Views", url: "/docs/schema/analytics-views" },
      ],
    },
  ],
  "lineage/lineage-auto": [
    {
      key: "blast-radius",
      label: "Start with blast radius",
      description:
        "Use the generated table-level map first when you need to know how wide the dependency ripple runs before debugging one metric or field.",
      items: [
        { title: "Table-level lineage", url: "#table-level-lineage" },
        { title: "Curated table replay", url: "/docs/lineage/table-lineage" },
        { title: "Endpoints", url: "/docs/endpoints" },
      ],
    },
    {
      key: "field-replay",
      label: "Then drop to field replay",
      description:
        "If the issue is one rename, metric, or key, move from the broad dependency map into the narrower column-level replay and naming guides.",
      items: [
        { title: "Column-level lineage", url: "#column-level-lineage" },
        { title: "Curated column replay", url: "/docs/lineage/column-lineage" },
        {
          title: "Field Reference",
          url: "/docs/data-dictionary/field-reference",
        },
      ],
    },
  ],
};

const helperHeadingTitles = new Set(["how to use this page"]);

function extractTocTitle(title: TOCItemType["title"]): string {
  if (typeof title === "string" || typeof title === "number") {
    return String(title).replace(/`/g, "").trim();
  }

  if (Array.isArray(title)) {
    return title
      .map((item) => extractTocTitle(item as TOCItemType["title"]))
      .join("");
  }

  if (title && typeof title === "object" && "props" in title) {
    const node = title as { props?: { children?: TOCItemType["title"] } };
    return extractTocTitle(node.props?.children ?? "");
  }

  return "";
}

function buildLayerClusters(items: Array<{ title: string; url: string }>) {
  return sortGeneratedSourceGroups(
    groupGeneratedItems(items, (item) => {
      const key = getGeneratedSourceGroupKey(item.title);

      return {
        key,
        label: humanizeGeneratedIdentifier(key),
        description:
          "Jump into the matching table family, then read the exact block.",
      };
    }),
  );
}

function buildStarClusters(items: Array<{ title: string; url: string }>) {
  return sortGeneratedStarGroups(
    groupGeneratedItems(items, (item) => {
      const key = getGeneratedStarGroupKey(item.title);
      const description =
        {
          dim: "Stable entity, calendar, venue, and lookup anchors.",
          fact: "Event and measurement tables at analyst-facing grain.",
          bridge: "Connector tables for many-to-many joins and role replay.",
          agg: "Derived aggregate surfaces for quicker trend reads.",
          analytics: "Shortcut surfaces that pre-join common analyst paths.",
        }[key] ?? "Generated public surfaces grouped by table family.";

      return {
        key,
        label: getGeneratedStarGroupLabel(key),
        description,
      };
    }),
  );
}

function getGeneratedScanClusters(
  pageKey: string,
  toc: TOCItemType[],
): GeneratedScanCluster[] {
  const manualClusters = generatedManualScanClusters[pageKey];

  if (manualClusters) {
    return manualClusters;
  }

  const items = toc
    .filter((item) => item.depth === 2 && item.url.startsWith("#"))
    .map((item) => ({
      title: extractTocTitle(item.title),
      url: item.url,
    }))
    .filter(
      (item) =>
        item.title.length > 0 &&
        !helperHeadingTitles.has(item.title.trim().toLowerCase()),
    );

  if (items.length < 4) {
    return [];
  }

  if (
    pageKey === "data-dictionary/star" ||
    pageKey === "schema/star-reference"
  ) {
    return buildStarClusters(items);
  }

  return buildLayerClusters(items);
}

export function DocsGeneratedScanSurface({
  slug,
  toc,
}: {
  slug?: string[];
  toc: TOCItemType[];
}) {
  const pageKey = slug?.join("/") ?? "";
  const meta = generatedScanSurfaceMeta[pageKey];

  if (!meta) {
    return null;
  }

  const clusters = getGeneratedScanClusters(pageKey, toc);
  const sourceLabel = meta.sourceLabel ?? "TOC-driven";

  if (clusters.length === 0) {
    return null;
  }

  const totalItems = clusters.reduce(
    (sum, cluster) => sum + cluster.items.length,
    0,
  );

  return (
    <section className="mt-8 space-y-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="nba-kicker">{meta.eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {meta.title}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {meta.description}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="primary">
            {totalItems} {meta.itemLabel}
          </Badge>
          <Badge variant="default">
            {clusters.length} {meta.groupingLabel}
          </Badge>
          <Badge variant="muted">{sourceLabel}</Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {clusters.map((cluster) => (
          <div key={cluster.key} className="border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                  {cluster.label}
                </div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {cluster.description}
                </p>
              </div>
              <div className="border border-border bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums text-foreground">
                {cluster.items.length}
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {cluster.items.slice(0, 6).map((item) => (
                <a
                  key={item.url}
                  href={item.url}
                  className="inline-flex items-center gap-2 border border-border bg-muted px-2 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <Blocks className="size-3" />
                  <span>{item.title}</span>
                </a>
              ))}
            </div>

            {cluster.items.length > 6 ? (
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                +{cluster.items.length - 6} more in the page TOC and section
                list.
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export function DocsGeneratedModules({ slug }: { slug?: string[] }) {
  const frame = getGeneratedPageFrame(slug);

  if (!frame) {
    return null;
  }

  return (
    <section className="mt-12 space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="nba-kicker">{frame.modulesEyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {frame.modulesTitle}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {frame.modulesDescription}
          </p>
        </div>
        <Badge variant="muted">{frame.modules.length} related routes</Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {frame.modules.map((module) => (
          <Link
            key={module.href}
            href={module.href}
            className="nba-related-card group border border-border bg-card p-4 md:p-5 transition-colors hover:bg-muted"
          >
            <div className="flex items-center justify-between gap-3">
              <Badge variant="outline">{module.label}</Badge>
              <ArrowRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
            </div>
            <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
              {module.title}
            </h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {module.description}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
