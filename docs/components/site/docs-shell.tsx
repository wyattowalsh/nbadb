import Image from "next/image";
import Link from "next/link";
import type { TOCItemType } from "fumadocs-core/toc";
import {
  ArrowRight,
  Blocks,
  Command,
  Search,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getDocsContextRail,
  getGeneratedPageFrame,
  getSectionMeta,
} from "@/lib/site-config";
import { getDocBreadcrumbs, humanizeSlug } from "@/lib/utils";

type DocsChromeProps = {
  slug?: string[];
  title: string;
  description?: string;
  tocCount?: number;
};

type DocsChromeSlugProps = {
  slug?: string[];
};


export function DocsNavBadge({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);

  return (
    <div className="hidden items-center gap-2 md:flex">
      <Link href={section.hubHref} className="nba-nav-route">
        <span className="nba-nav-route-section">{section.label}</span>
        <span aria-hidden="true" className="text-muted-foreground/50">
          /
        </span>
        <span className="nba-nav-route-cue">{section.cue}</span>
      </Link>
      <div className="nba-nav-command">
        <Command className="size-3.5" />
        <span>Search</span>
        <kbd>⌘K</kbd>
      </div>
    </div>
  );
}

export function DocsSidebarBanner({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);
  const currentPath = slug?.length ? `/docs/${slug.join("/")}` : "/docs";
  const quickLinks = section.quickLinks
    .filter((link) => link.href !== currentPath)
    .slice(0, 2);

  return (
    <div className="nba-sidebar-banner border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          <Image src="/logo.png" alt="" width={16} height={16} className="h-4 w-auto" />
          nbadb
        </span>
        <Badge variant="default">{section.cue}</Badge>
      </div>
      <div className="mt-3 space-y-3">
        <div>
          <p className="nba-kicker">{section.eyebrow}</p>
          <h2 className="mt-2 text-base font-semibold tracking-tight text-foreground">
            {section.label}
          </h2>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {section.blurb}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {section.stats.slice(0, 2).map((stat) => (
            <div key={stat.label} className="nba-sidebar-stat">
              <span className="nba-sidebar-stat-value">{stat.value}</span>
              <span className="nba-sidebar-stat-label">{stat.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-2">
        <Button asChild size="sm" className="justify-between">
          <Link href={section.hubHref}>
            {section.id === "core" ? "Docs front door" : "Section hub"}
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>

        {quickLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="nba-sidebar-route-link"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="nba-sidebar-route-eyebrow">Quick route</div>
                <div className="mt-1 text-sm font-semibold text-foreground">
                  {link.title}
                </div>
              </div>
              <ArrowRight className="mt-0.5 size-3.5 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {link.description}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function DocsSidebarFooter({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);
  const searchPrompt = section.prompts[0];

  return (
    <div className="nba-sidebar-footer space-y-2 text-xs">
      <div className="flex flex-wrap gap-2">
        <Badge variant="default">{section.label}</Badge>
        <Badge variant="muted">{section.cue}</Badge>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <a href="https://github.com/wyattowalsh/nba-db" target="_blank" rel="noopener noreferrer">
          <img src="https://img.shields.io/github/stars/wyattowalsh/nba-db?style=flat-square&label=stars&color=orange" alt="GitHub stars" className="h-5" loading="lazy" />
        </a>
        <a href="https://pypi.org/project/nbadb/" target="_blank" rel="noopener noreferrer">
          <img src="https://img.shields.io/pypi/v/nbadb?style=flat-square&label=pypi" alt="PyPI version" className="h-5" loading="lazy" />
        </a>
      </div>
      <div className="nba-sidebar-prompt">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-primary">
          Try in search
        </div>
        <div className="mt-1 font-mono text-[0.78rem] text-foreground">
          {searchPrompt.query}
        </div>
      </div>
      <p className="text-muted-foreground">
        <kbd>⌘K</kbd> to search tables, endpoints, guides, and diagrams.
      </p>
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
  const breadcrumbs = getDocBreadcrumbs(slug);
  const currentPath = slug?.length ? `/docs/${slug.join("/")}` : "/docs";
  const currentLabel = slug?.length
    ? humanizeSlug(slug[slug.length - 1])
    : "Index";
  const leadLink =
    currentPath === section.hubHref
      ? section.quickLinks[0]
      : {
          title: section.id === "core" ? "Docs front door" : "Section hub",
          href: section.hubHref,
          description: section.blurb,
        };
  const relatedLinks = section.quickLinks
    .filter((link) => link.href !== currentPath && link.href !== leadLink?.href)
    .slice(0, 2);

  return (
    <section className="nba-page-hero @container">
      <div className="nba-page-hero-shell">
        <div>
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

          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="primary">{section.label}</Badge>
              <Badge variant="default">{section.cue}</Badge>
              {tocCount > 0 ? <Badge variant="muted">{tocCount} guideposts</Badge> : null}
            </div>

            <div>
              <p className="nba-kicker">{section.eyebrow}</p>
              <h1 className="mt-3 text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                {title}
              </h1>
            </div>
            {description ? (
              <p className="max-w-3xl text-sm leading-7 text-muted-foreground" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
                {description}
              </p>
            ) : null}

            <div className="nba-page-hero-actions">
              {leadLink ? (
                <Button asChild size="sm">
                  <Link href={leadLink.href}>
                    {leadLink.title}
                    <ArrowRight className="size-3.5" />
                  </Link>
                </Button>
              ) : null}

              {relatedLinks.map((link) => (
                <Link key={link.href} href={link.href} className="nba-page-hero-link">
                  <span>{link.title}</span>
                  <ArrowRight className="size-3.5" />
                </Link>
              ))}
            </div>

            <div className="nba-page-hero-stats">
              {section.stats.map((stat) => (
                <div key={stat.label} className="nba-page-hero-stat-card">
                  <span className="nba-page-hero-stat-value">{stat.value}</span>
                  <span className="nba-page-hero-stat-label">{stat.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="nba-page-hero-mark" aria-hidden="true">
          <Image src="/logo-600.png" alt="" width={600} height={600} className="h-auto w-full" priority />
          <div className="nba-page-hero-stat">
            <span className="nba-kicker">{section.cue}</span>
            <span>{currentLabel}</span>
          </div>
        </div>
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
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {frame.steps.map((step, index) => (
              <div
                key={step.title}
                className="border border-border bg-muted px-3 py-3"
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

      <aside className="border border-border bg-card p-4">
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
          <Badge variant="primary">{totalItems} {meta.itemLabel}</Badge>
          <Badge variant="default">{clusters.length} {meta.groupingLabel}</Badge>
          <Badge variant="muted">{sourceLabel}</Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {clusters.map((cluster) => (
          <div
            key={cluster.key}
            className="border border-border bg-card p-4"
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
            className="nba-related-card group border border-border bg-card p-4 transition-colors hover:bg-muted"
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
              className="nba-related-card group border border-border bg-card p-4 transition-colors hover:bg-muted"
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

        <aside className="nba-discovery-panel border border-border bg-card p-4">
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
                className="nba-discovery-prompt border border-border bg-muted px-3 py-2"
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
