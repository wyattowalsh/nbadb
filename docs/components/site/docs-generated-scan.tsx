import type { TOCItemType } from "fumadocs-core/toc";
import { Blocks } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  getGeneratedSourceGroupKey,
  getGeneratedStarGroupKey,
  getGeneratedStarGroupLabel,
  groupGeneratedItems,
  humanizeGeneratedIdentifier,
  sortGeneratedSourceGroups,
  sortGeneratedStarGroups,
} from "@/lib/generated-grouping";

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
