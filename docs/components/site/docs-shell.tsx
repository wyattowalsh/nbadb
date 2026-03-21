import Link from "next/link";
import type { TOCItemType } from "fumadocs-core/toc";
import {
  ArrowRight,
  BookOpenText,
  Blocks,
  Command,
  Database,
  LayoutGrid,
  Network,
  Radar,
  Route,
  Search,
  Trophy,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getDocsContextRail,
  getGeneratedPageFrame,
  getSectionMeta,
  type SectionId,
} from "@/lib/site-config";
import { cn, getDocBreadcrumbs, humanizeSlug } from "@/lib/utils";

type DocsChromeProps = {
  slug?: string[];
  title: string;
  description?: string;
  tocCount?: number;
};

const sectionIcons: Record<SectionId, typeof Radar> = {
  core: Radar,
  schema: Database,
  "data-dictionary": BookOpenText,
  diagrams: LayoutGrid,
  endpoints: Trophy,
  lineage: Network,
  guides: Route,
};

export function DocsNavBadge() {
  return (
    <div className="hidden items-center gap-2 md:flex">
      <Badge variant="accent" className="lg:text-[0.6rem] lg:tracking-[0.3em]">
        Film Room Nav
      </Badge>
      <div className="nba-nav-command">
        <Command className="size-3.5" />
        <span>Search</span>
        <kbd>⌘K</kbd>
      </div>
    </div>
  );
}

export function DocsSidebarBanner() {
  return (
    <div className="nba-surface rounded-[1.8rem] p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[0.65rem] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
          <Radar className="size-3.5 text-primary" />
          Arena Data Lab
        </div>
        <Badge variant="board">141 tables</Badge>
      </div>
      <p className="mt-3 text-sm leading-6 text-foreground/90">
        A film-room shell for data people: warehouse maps, endpoint scouting,
        lineage chains, operational playbooks, and visual prompt packs in one
        possession.
      </p>
      <div className="mt-4 grid gap-2">
        <Button asChild size="sm" className="justify-between rounded-2xl">
          <Link href="/docs/guides/analytics-quickstart">
            Quickstart
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
        <Button
          asChild
          variant="tint"
          size="sm"
          className="justify-between rounded-2xl"
        >
          <Link href="/docs/diagrams/pipeline-flow">
            Pipeline flow
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
        <Button
          asChild
          variant="outline"
          size="sm"
          className="justify-between rounded-2xl"
        >
          <Link href="/docs/guides/visual-asset-prompt-pack">
            Asset prompt pack
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {[
          { label: "Schema", href: "/docs/schema" },
          { label: "Lineage", href: "/docs/lineage" },
          { label: "OG Kit", href: "/docs/guides/visual-asset-prompt-pack" },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-2xl border border-border/70 bg-background/70 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:bg-accent/12 hover:text-foreground"
          >
            {item.label}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function DocsSidebarFooter() {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-2">
        <Badge variant="signal">131 endpoints</Badge>
        <Badge variant="muted">47 docs pages</Badge>
        <Badge variant="board">11 guides</Badge>
      </div>
      <p className="text-muted-foreground">
        Built for analysts, operators, and anyone who wants basketball data to
        feel composable instead of chaotic, shareable instead of sterile, and
        visually consistent across docs, cards, and social surfaces.
      </p>
      <div className="nba-search-card rounded-[1.4rem] p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-foreground">
          <Search className="size-3.5 text-primary" />
          Search lane
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          Use <kbd>⌘K</kbd> to jump straight to tables, guides, diagrams, and
          endpoint families.
        </p>
      </div>
      <Link
        href="/docs/guides/visual-asset-prompt-pack"
        className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary"
      >
        Build share cards and prompts
        <ArrowRight className="size-3.5" />
      </Link>
      <Link
        href="/docs/guides/role-based-onboarding-hub"
        className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary"
      >
        Start with role-based onboarding
        <ArrowRight className="size-3.5" />
      </Link>
    </div>
  );
}

export function DocsPageHero({
  slug,
  title,
  description,
  tocCount = 0,
}: DocsChromeProps) {
  const section = getSectionMeta(slug);
  const contextRail = getDocsContextRail(slug);
  const Icon = sectionIcons[section.id];
  const breadcrumbs = getDocBreadcrumbs(slug);
  const currentLabel = slug?.length
    ? humanizeSlug(slug[slug.length - 1])
    : "Index";

  return (
    <section className="nba-page-hero @container">
      <nav aria-label="Breadcrumb">
        <ol className="flex list-none flex-wrap items-center gap-2 p-0">
          {breadcrumbs.map((crumb, index) => {
            const isCurrent = index === breadcrumbs.length - 1;

            return (
              <li key={crumb.href} className="flex items-center gap-2">
                {isCurrent ? (
                  <span aria-current="page" className="nba-crumb-current">
                    {crumb.label}
                  </span>
                ) : (
                  <Link href={crumb.href} className="nba-crumb-link">
                    {crumb.label}
                  </Link>
                )}
                {index < breadcrumbs.length - 1 ? (
                  <span aria-hidden="true" className="text-muted-foreground/60">
                    /
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_21rem] xl:items-start">
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <Badge variant="signal">{section.label}</Badge>
            <Badge variant="board">{section.cue}</Badge>
            <Badge variant="muted">{currentLabel}</Badge>
            <Badge variant="muted">{Math.max(tocCount, 1)} waypoints</Badge>
          </div>

          <div className="flex items-start gap-4">
            <div
              className={cn(
                "hidden size-15 shrink-0 items-center justify-center rounded-[1.65rem] border border-border/60 bg-linear-to-br shadow-[0_20px_48px_-28px_color-mix(in_oklab,var(--foreground)_55%,transparent)] md:flex",
                section.toneClass,
              )}
            >
              <Icon className="size-7 text-foreground" />
            </div>
            <div className="space-y-3">
              <p className="nba-kicker">{section.eyebrow}</p>
              <h1 className="text-balance text-4xl font-semibold tracking-tight text-foreground md:text-5xl xl:text-[3.4rem]">
                {title}
              </h1>
              {description ? (
                <p className="max-w-3xl text-pretty text-base leading-7 text-muted-foreground md:text-lg">
                  {description}
                </p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button asChild size="sm">
              <Link href={section.hubHref}>
                Browse {section.label}
                <ArrowRight className="size-3.5" />
              </Link>
            </Button>
            <Button asChild size="sm" variant="tint">
              <Link
                href={
                  contextRail.links[0]?.href ??
                  section.quickLinks[0]?.href ??
                  "/docs"
                }
              >
                Next best page
                <ArrowRight className="size-3.5" />
              </Link>
            </Button>
            <Button asChild size="sm" variant="ghost">
              <Link href="/docs">Open docs map</Link>
            </Button>
          </div>
        </div>

        <aside className="nba-surface rounded-[1.6rem] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="nba-kicker">Scouting report</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                Section context
              </h2>
            </div>
            <Icon className="size-5 text-primary" />
          </div>

          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {section.blurb}
          </p>

          <div className="mt-4 grid gap-2 @md:grid-cols-3 xl:grid-cols-1">
            {section.stats.map((stat) => (
              <div
                key={stat.label}
                className="rounded-[1.1rem] border border-border/70 bg-background/72 px-3 py-2"
              >
                <div className="nba-scoreboard-value text-lg text-foreground">
                  {stat.value}
                </div>
                <div className="nba-metric-label mt-1">{stat.label}</div>
              </div>
            ))}
          </div>

          <div className="mt-5 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <Blocks className="size-3.5" />
              Route stack
            </div>
            <div className="grid gap-2">
              {section.quickLinks.slice(0, 3).map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="rounded-[1.1rem] border border-border/70 bg-background/72 px-3 py-3 transition-colors hover:bg-accent/12"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                      {link.title}
                    </div>
                    <ArrowRight className="size-3.5 text-muted-foreground" />
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {link.description}
                  </p>
                </Link>
              ))}
            </div>
          </div>

          <div className="mt-5 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <Search className="size-3.5" />
              Search lanes
            </div>
            <div className="grid gap-2">
              {section.prompts.slice(0, 2).map((prompt) => (
                <div
                  key={prompt.query}
                  className="rounded-[1.1rem] border border-border/70 bg-background/72 px-3 py-3"
                >
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    {prompt.label}
                  </div>
                  <div className="mt-1 font-mono text-[0.78rem] text-foreground">
                    {prompt.query}
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {prompt.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

export function DocsGeneratedEntrySurface({
  slug,
}: {
  slug?: string[];
}) {
  const frame = getGeneratedPageFrame(slug);

  if (!frame) {
    return null;
  }

  return (
    <section className="mt-8 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="nba-surface rounded-[1.8rem] p-5 md:p-6">
        <div className="flex flex-wrap gap-2">
          <Badge variant="signal">Generated page</Badge>
          <Badge variant="board">Command-owned</Badge>
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
              className="rounded-[1.25rem] border border-border/70 bg-background/72 px-4 py-3"
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
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {frame.steps.map((step, index) => (
              <div
                key={step.title}
                className="rounded-[1.25rem] border border-border/70 bg-background/72 px-4 py-4"
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

      <aside className="nba-search-card rounded-[1.8rem] p-5">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-foreground">
          <Command className="size-3.5 text-primary" />
          Generator boundary
        </div>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {frame.ownershipNote}
        </p>
        <div className="mt-4 rounded-[1.2rem] border border-border/70 bg-background/72 p-4">
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
        { title: "Field Reference", url: "/docs/data-dictionary/field-reference" },
      ],
    },
  ],
};

const helperHeadingTitles = new Set(["how to use this page"]);

const tableFamilyMeta = {
  dim: {
    label: "Dimensions",
    description: "Stable entity, calendar, venue, and lookup anchors.",
  },
  fact: {
    label: "Facts",
    description: "Event and measurement tables at analyst-facing grain.",
  },
  bridge: {
    label: "Bridges",
    description: "Connector tables for many-to-many joins and role replay.",
  },
  agg: {
    label: "Rollups",
    description: "Derived aggregate surfaces for quicker trend reads.",
  },
  analytics: {
    label: "Analytics Views",
    description: "Shortcut surfaces that pre-join common analyst paths.",
  },
} as const;

function extractTocTitle(title: TOCItemType["title"]): string {
  if (typeof title === "string" || typeof title === "number") {
    return String(title).replace(/`/g, "").trim();
  }

  if (Array.isArray(title)) {
    return title.map((item) => extractTocTitle(item as TOCItemType["title"])).join("");
  }

  if (title && typeof title === "object" && "props" in title) {
    const node = title as { props?: { children?: TOCItemType["title"] } };
    return extractTocTitle(node.props?.children ?? "");
  }

  return "";
}

function humanizeIdentifier(value: string) {
  return humanizeSlug(value.replace(/_/g, "-"));
}

function getLayerClusterKey(tableName: string) {
  const normalized = tableName.replace(/^(raw|stg|staging)_/, "");
  const parts = normalized.split("_").filter(Boolean);

  if (parts.length === 0) {
    return tableName;
  }

  return parts.slice(0, Math.min(parts.length, 2)).join("_");
}

function buildLayerClusters(items: Array<{ title: string; url: string }>) {
  const clusters = new Map<string, GeneratedScanCluster>();

  for (const item of items) {
    const key = getLayerClusterKey(item.title);
    const existing = clusters.get(key);

    if (existing) {
      existing.items.push(item);
      continue;
    }

    clusters.set(key, {
      key,
      label: humanizeIdentifier(key),
      description: "Jump into the matching table family, then read the exact block.",
      items: [item],
    });
  }

  return Array.from(clusters.values()).sort((left, right) => {
    if (right.items.length !== left.items.length) {
      return right.items.length - left.items.length;
    }

    return left.label.localeCompare(right.label);
  });
}

function buildStarClusters(items: Array<{ title: string; url: string }>) {
  const clusters = new Map<string, GeneratedScanCluster>();

  for (const item of items) {
    const [family = "other"] = item.title.split("_");
    const familyMeta =
      tableFamilyMeta[family as keyof typeof tableFamilyMeta] ?? {
        label: humanizeIdentifier(family),
        description: "Generated public surfaces grouped by table family.",
      };
    const existing = clusters.get(family);

    if (existing) {
      existing.items.push(item);
      continue;
    }

    clusters.set(family, {
      key: family,
      label: familyMeta.label,
      description: familyMeta.description,
      items: [item],
    });
  }

  const familyOrder = Object.keys(tableFamilyMeta);

  return Array.from(clusters.values()).sort((left, right) => {
    const leftIndex = familyOrder.indexOf(left.key);
    const rightIndex = familyOrder.indexOf(right.key);

    if (leftIndex === -1 || rightIndex === -1) {
      return left.label.localeCompare(right.label);
    }

    return leftIndex - rightIndex;
  });
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

  if (pageKey === "data-dictionary/star" || pageKey === "schema/star-reference") {
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

  const totalItems = clusters.reduce((sum, cluster) => sum + cluster.items.length, 0);

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
          <Badge variant="signal">{totalItems} {meta.itemLabel}</Badge>
          <Badge variant="board">{clusters.length} {meta.groupingLabel}</Badge>
          <Badge variant="muted">{sourceLabel}</Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {clusters.map((cluster) => (
          <div
            key={cluster.key}
            className="nba-surface rounded-[1.5rem] p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                  {cluster.label}
                </div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {cluster.description}
                </p>
              </div>
              <div className="rounded-full border border-border/70 bg-background/72 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-foreground">
                {cluster.items.length}
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {cluster.items.slice(0, 6).map((item) => (
                <a
                  key={item.url}
                  href={item.url}
                  className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/72 px-3 py-2 text-xs font-semibold text-muted-foreground transition-colors hover:border-primary/35 hover:text-foreground"
                >
                  <Blocks className="size-3" />
                  <span>{item.title}</span>
                </a>
              ))}
            </div>

            {cluster.items.length > 6 ? (
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                +{cluster.items.length - 6} more in the page TOC and section list.
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
      <div>
        <p className="nba-kicker">{frame.modulesEyebrow}</p>
        <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          {frame.modulesTitle}
        </h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          {frame.modulesDescription}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {frame.modules.map((module) => (
          <Link
            key={module.href}
            href={module.href}
            className="nba-surface group rounded-[1.5rem] p-5 transition-transform duration-200 hover:-translate-y-0.5"
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

export function DocsContextRail({ slug }: { slug?: string[] }) {
  const section = getSectionMeta(slug);
  const contextRail = getDocsContextRail(slug);
  const currentPath = slug?.length ? `/docs/${slug.join("/")}` : "/docs";
  const links = contextRail.links
    .filter((link) => link.href !== currentPath)
    .slice(0, 3);

  const getLinkBadge = (href: string) => {
    if (!href.startsWith("/docs")) {
      return section.label;
    }

    const linkedSlug = href
      .replace(/^\/docs\/?/, "")
      .split("/")
      .filter(Boolean);
    return getSectionMeta(linkedSlug.length ? linkedSlug : undefined).label;
  };

  return (
    <section className="mt-12 space-y-4">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="nba-kicker">{contextRail.eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {contextRail.title}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {contextRail.description}
          </p>
        </div>
        <Button asChild size="sm" variant="ghost" className="max-sm:hidden">
          <Link href={contextRail.hubHref}>{contextRail.hubLabel}</Link>
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]">
        <div className="grid gap-4 md:grid-cols-3">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="nba-surface group rounded-[1.5rem] p-5 transition-transform duration-200 hover:-translate-y-0.5"
            >
              <div className="flex items-center justify-between gap-3">
                <Badge variant="outline">{getLinkBadge(link.href)}</Badge>
                <ArrowRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
              </div>
              <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
                {link.title}
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {link.description}
              </p>
            </Link>
          ))}
        </div>

        <aside className="nba-search-card rounded-[1.7rem] p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="nba-kicker">Search and discovery</p>
              <h3 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                Prompt the surface
              </h3>
            </div>
            <Search className="size-5 text-primary" />
          </div>
          <div className="mt-4 space-y-3">
            {contextRail.prompts.map((prompt) => (
              <div
                key={prompt.query}
                className="rounded-[1.15rem] border border-border/70 bg-background/70 px-4 py-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    {prompt.label}
                  </div>
                  <span className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    ⌘K
                  </span>
                </div>
                <div className="mt-1 font-mono text-[0.8rem] text-foreground">
                  {prompt.query}
                </div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {prompt.description}
                </p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}
