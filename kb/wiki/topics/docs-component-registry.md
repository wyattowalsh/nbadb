---
title: Docs Component Registry
tags:
  - kb
  - topics
  - docs
  - frontend
  - mdx
aliases:
  - Docs MDX Registry
  - Docs Chrome Registry
kind: concept
status: active
updated: 2026-04-14
source_count: 16
---

# Docs Component Registry

Use this note when you need to answer three questions quickly: which MDX components are actually registered, which docs chrome pieces wrap authored pages, and where those pieces show up in the live `/docs/...` routes.

## Render path
1. `docs/source.config.ts` declares `content/docs` as the MDX source tree and enables `remarkMdxMermaid`.
2. `docs/lib/source.ts` turns that MDX tree into the Fumadocs loader with `baseUrl: "/docs"`.
3. `docs/app/docs/{catch-all}/page.tsx` resolves the page by slug, pulls its compiled MDX body, and renders it through `MDXContent`.
4. `docs/components/mdx.tsx` is the registry boundary: it merges Fumadocs defaults with repo-specific prose components and interactive widgets.
5. `docs/app/docs/{catch-all}/layout.tsx` wraps every docs route in `DocsLayout` plus the site chrome exported from `docs/components/site/docs-shell.tsx`.

## Registry lanes
| Lane | Source of truth | What it contributes | Notes |
| --- | --- | --- | --- |
| Fumadocs defaults | `docs/components/mdx.tsx` via `fumadocs-ui/mdx` | `Callout`, `Tabs`, `Cards`, `Steps`, `Accordions`, and the rest of the stock MDX UI | available to authored MDX without local imports |
| Repo prose primitives | `docs/components/mdx.tsx` | `StatPill`, `StatGrid`, `ScoutCard`, `DataColumns`, `CommandBlock`, `MetricRow`, `Metric`, `CourtDivider`, `InsightCard`, `WarningCard`, plus the `blockquote` override | these are the main authored-docs narrative building blocks |
| Mermaid | `docs/components/mdx.tsx`, `docs/components/mdx/mermaid.tsx`, `docs/source.config.ts` | `Mermaid` component and automatic fenced-`mermaid` support | client-rendered, theme-aware, zoomable, with fallback/error states |
| Heavy interactive widgets | `docs/components/mdx/dynamic-charts.tsx` | `SqlPlayground`, `ObservablePlot`, `ShotChart`, `GameFlow`, `PlayerCompare`, `SeasonTrend`, `DistributionPlot`, `HeatmapGrid`, `SchemaExplorer`, `LineageExplorer` | loaded with `next/dynamic`, `ssr: false`, placeholder shell, and widget error boundary |

## MDX widget notes
| Widget family | Backing file | Practical role | Current authored-page footprint |
| --- | --- | --- | --- |
| `SqlPlayground` | `docs/components/mdx/sql-playground.tsx` | browser DuckDB-WASM sandbox with example buttons, Parquet registration, query cancel/reset, table-or-chart results, and copy actions | used twice on `docs/content/docs/playground.mdx` -> `/docs/playground` |
| `Mermaid` | `docs/components/mdx/mermaid.tsx` | client SVG render with theme token mapping, zoom/pan, render timeout, and source-preview fallback | used directly in `ops/visual-asset-prompt-pack.mdx`; also reached indirectly from fenced `mermaid` blocks |
| `ObservablePlot` base | `docs/components/mdx/observable-plot.tsx` | generic Observable Plot shell and chart mount | registered, but no direct hand-authored `<ObservablePlot ... />` usage found in the pages checked here |
| `ShotChart` | `docs/components/mdx/observable-plot.tsx` | NBA court overlay for shot-location dots | used on `start/shot-chart-analysis.mdx` -> `/docs/start/shot-chart-analysis` |
| `GameFlow`, `PlayerCompare`, `SeasonTrend`, `DistributionPlot`, `HeatmapGrid` | `docs/components/mdx/observable-plot.tsx` | prebuilt statistical chart variants | registered, but no hand-authored usage found in the current docs pages checked here |
| `SchemaExplorer`, `LineageExplorer` | dynamic wrappers around dedicated explorer files | heavier interactive exploration widgets | registered, but no hand-authored usage found in `docs/content/docs/**/*.mdx` |

## Mermaid mapping in authored pages
| Authoring pattern | Route examples | How it resolves |
| --- | --- | --- |
| fenced code block with language `mermaid` | `start/architecture.mdx`, `model/schema/index.mdx`, `model/diagrams/er-diagram.mdx`, `model/lineage/table-lineage.mdx`, `model/lineage/column-lineage.mdx` | `remarkMdxMermaid` rewrites the fence to the registered `Mermaid` component |
| explicit `<Mermaid chart={...} />` | `ops/visual-asset-prompt-pack.mdx` | authored page calls the registry component directly |

## Docs chrome pieces
| Layer | Files | Applies to | What it does |
| --- | --- | --- | --- |
| Barrel export | `docs/components/site/docs-shell.tsx` | import surface for layout/page routes | re-exports nav, hero, generated-page surfaces, and context rail |
| Global docs layout chrome | `docs/app/docs/{catch-all}/layout.tsx`, `docs/components/site/docs-nav.tsx` | every `/docs/**` route | `DocsLayout`, brand header, `DocsNavBadge`, `DocsSidebarBanner`, `DocsSidebarFooter`, footer, theme switch |
| Per-page chrome | `docs/app/docs/{catch-all}/page.tsx`, `docs/components/site/docs-page-hero.tsx`, `docs/components/site/docs-context-rail.tsx` | every docs content page | breadcrumbs, section badges, stats, ownership/updated metadata, MDX body shell, and related/discovery rail |
| Generated-page chrome | `docs/components/site/docs-generated-entry.tsx`, `docs-generated-modules.tsx`, `docs-generated-scan.tsx`, `docs-generated-coverage.tsx` | generated docs surfaces and coverage-aware schema/lineage routes | generator boundary callouts, quick-scan clusters, related modules, and schema-coverage caveats |

## How authored pages map to the chrome
- Every page under `docs/content/docs/**` becomes a `/docs/...` route through `docs/lib/source.ts` and `source.getPage()`.
- Hand-authored pages always receive the shared layout chrome plus `DocsPageHero`, the MDX body shell, and a trailing `DocsContextRail`.
- Generated pages still render the MDX body, but `docs/app/docs/{catch-all}/page.tsx` inserts generated-entry, scan, modules, and coverage surfaces when `getGeneratedPageFrame(slug)` or page-key checks say the route is command-owned.
- `docs/content/docs/playground.mdx` is the clearest authored example of registry-plus-chrome working together: the page body contributes two `SqlPlayground` instances, while the route wrapper still adds the hero and discovery rail around them.

## Maintainer cues
- Add or rename MDX-callable components in `docs/components/mdx.tsx`; that file is the registry contract.
- Put heavy client-only widgets behind `docs/components/mdx/dynamic-charts.tsx` so they stay SSR-disabled and error-bounded.
- Prefer fenced `mermaid` blocks for normal diagrams; use explicit `<Mermaid>` only when the chart string needs programmatic construction.
- Change section/page chrome in the docs catch-all route files under `docs/app/docs/` or `docs/components/site/docs-*.tsx`, not in authored MDX files.

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/playground-lane|Playground Lane]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| docs app structure, MDX registry, interactive component list, docs chrome inventory | `docs/AGENTS.md` | primary docs-app operating contract |
| MDX registry boundary and local prose components | `docs/components/mdx.tsx` | canonical registry file |
| lazy widget wrappers, SSR disablement, placeholders, error boundary | `docs/components/mdx/dynamic-charts.tsx` | interactive widget loading lane |
| SQL playground mechanics and UI behaviors | `docs/components/mdx/sql-playground.tsx` | widget implementation |
| Mermaid fallback, theming, zoom/pan, and render lifecycle | `docs/components/mdx/mermaid.tsx` | widget implementation |
| Observable Plot base wrapper and chart variants | `docs/components/mdx/observable-plot.tsx` | plot implementation |
| fenced Mermaid transform | `docs/source.config.ts` | `remarkMdxMermaid` wiring |
| MDX tree to `/docs` route mapping | `docs/lib/source.ts` | Fumadocs loader contract |
| docs route layout shell | `docs/app/docs/{catch-all}/layout.tsx` | always-on chrome |
| docs page renderer and generated-page insertions | `docs/app/docs/{catch-all}/page.tsx` | page assembly order |
| docs-shell barrel export | `docs/components/site/docs-shell.tsx` | import surface for site chrome |
| nav badge and sidebar chrome | `docs/components/site/docs-nav.tsx` | top nav and sidebar pieces |
| page hero contract | `docs/components/site/docs-page-hero.tsx` | hero layer |
| related/discovery rail | `docs/components/site/docs-context-rail.tsx` | post-body route guidance |
| generated entry/modules/scan surfaces | `docs/components/site/docs-generated-entry.tsx`; `docs/components/site/docs-generated-modules.tsx`; `docs/components/site/docs-generated-scan.tsx`; `docs/components/site/docs-generated-coverage.tsx` | generated-page chrome |
| concrete authored-page usage of `SqlPlayground`, `ShotChart`, and direct/fenced Mermaid | `docs/content/docs/playground.mdx`; `docs/content/docs/start/shot-chart-analysis.mdx`; `docs/content/docs/ops/visual-asset-prompt-pack.mdx`; `docs/content/docs/model/schema/index.mdx`; `docs/content/docs/model/diagrams/er-diagram.mdx`; `docs/content/docs/model/lineage/table-lineage.mdx`; `docs/content/docs/model/lineage/column-lineage.mdx` | current page-level examples |
