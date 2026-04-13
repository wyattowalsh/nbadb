# Docs Site — Agent Instructions

## 1. Framework

- **Fumadocs 16** (fumadocs-core 16.7.4, fumadocs-mdx 14.2.11, fumadocs-ui 16.7.4)
- **Next.js 16.2.1** with App Router
- **pnpm** (package manager)
- **Tailwind CSS v4.2** (v4 `@theme` syntax, no `tailwind.config.js`)
- **Mermaid 11** for diagrams (client-side rendering via custom component)
- **DuckDB-WASM** for in-browser SQL playground
- **Observable Plot** for data visualization (shot charts, game flow, heatmaps, comparisons, trends, distributions)
- **Recharts** for admin dashboard charts
- **class-variance-authority (CVA)** for variant-driven UI components

## 2. Content Structure

```text
docs/
├── app/
│   ├── (home)/page.tsx              # Landing page (hero, scoreboard, topic grid, quick start)
│   ├── (admin)/admin/               # Admin route group (auth-gated)
│   │   ├── layout.tsx               # Admin shell layout
│   │   ├── login/page.tsx           # Login page
│   │   └── pipeline/               # Pipeline monitoring dashboard
│   │       ├── page.tsx
│   │       └── pipeline-charts.tsx
│   ├── layout.tsx                   # Root layout (RootProvider, fonts, metadata)
│   ├── global.css                   # 1190-line custom design system
│   ├── docs/[[...slug]]/
│   │   ├── page.tsx                 # Docs page renderer (hero + MDX body + context rail)
│   │   └── layout.tsx               # Docs sidebar layout (DocsLayout, nav links)
│   └── docs-og/[[...slug]]/route.tsx # Dynamic OG image generation
├── components/
│   ├── mdx.tsx                      # MDX component registry (getMDXComponents)
│   ├── mdx/
│   │   ├── mermaid.tsx              # Zoomable Mermaid renderer (zoom/pan, theme-aware)
│   │   ├── sql-playground.tsx       # DuckDB-WASM SQL sandbox
│   │   └── observable-plot.tsx      # ObservablePlot, ShotChart, GameFlow, PlayerCompare,
│   │                                #   SeasonTrend, DistributionPlot, HeatmapGrid
│   ├── site/
│   │   ├── counter.tsx              # Animated count-up (IntersectionObserver)
│   │   └── docs-shell.tsx           # Docs chrome (hero, sidebar, context rail, etc.)
│   ├── ui/
│   │   ├── badge.tsx                # CVA badge (6 variants)
│   │   ├── button.tsx               # CVA button (4 variants, 4 sizes, asChild)
│   │   ├── card.tsx
│   │   ├── tabs.tsx
│   │   └── skeleton.tsx
│   └── admin/                       # 13 admin dashboard components
│       ├── admin-shell.tsx, admin-nav.tsx
│       ├── kpi-card.tsx, sparkline-card.tsx, tracker-bar.tsx
│       ├── chart-area.tsx, chart-bar.tsx, chart-donut.tsx
│       ├── bar-list.tsx, content-freshness.tsx, freshness-heatmap.tsx
│       ├── status-dot.tsx, data-table.tsx
├── content/docs/                    # MDX content (7 sections, 49 pages)
│   ├── meta.json                    # Root nav ordering (Getting Started / Reference / Guides)
│   ├── index.mdx                    # Docs landing
│   ├── installation.mdx, architecture.mdx, cli-reference.mdx
│   ├── playground.mdx               # DuckDB-WASM SQL sandbox page
│   ├── schema/                      # Star schema reference (9 pages)
│   ├── data-dictionary/             # Field-level documentation (6 pages + glossary)
│   ├── diagrams/                    # ER, pipeline, endpoint diagrams (5 pages)
│   ├── endpoints/                   # API endpoint documentation (8 pages)
│   ├── lineage/                     # Data lineage traces (4 pages; machine JSON lives in lib/generated/)
│   └── guides/                      # User and operator guides (13 pages)
├── lib/
│   ├── site-config.ts               # Section metadata, hero signals, and context-rail data
│   ├── site-metrics.generated.ts    # Auto-generated homepage scoreboard metrics
│   ├── source.ts                    # Content loader (fumadocs-core/source)
│   ├── duckdb.ts                    # DuckDB-WASM singleton, query runner, Parquet loader
│   ├── use-zoom-pan.ts              # Zoom/pan hook for Mermaid diagrams
│   ├── utils.ts                     # cn() className helper, breadcrumb utils
│   └── admin/                       # Admin data fetchers and types
│       ├── pipeline.ts
│       └── types.ts
├── proxy.ts                         # Admin auth guard / request interception (HMAC session cookie, 24h TTL)
├── source.config.ts                 # fumadocs-mdx config (remarkMdxMermaid plugin)
├── next.config.mjs                  # Next.js config (createMDX wrapper)
└── package.json
```

## 3. Navigation

- Sidebar ordering is controlled by `meta.json` files in each content directory
- Root `meta.json` defines three section groups with `---Separator---` syntax:
  - **Getting Started** — index, installation, architecture, cli-reference
  - **Reference** — schema, data-dictionary, diagrams, endpoints, lineage
  - **Guides** — playground, guides
- Subsection `meta.json` uses `pages` arrays with `---` separators for ordering
- `guides/meta.json` groups content into **Onboarding**, **Tutorials**, **Operations**, **Troubleshooting**, and **Maintainers**
- Prefix `...` references a subfolder (e.g., `...schema` expands `schema/` contents)

## 4. Auto-Generated Pages — DO NOT HAND-EDIT

These pages are generated by `uv run nbadb docs-autogen --docs-root docs/content/docs`:

- `diagrams/er-auto.mdx` — ER diagram from schema definitions
- `lineage/lineage-auto.mdx` — Lineage from transform dependencies

Hand-authored companion pages exist alongside them (er-diagram.mdx, table-lineage.mdx, column-lineage.mdx).

`lib/site-metrics.generated.ts` is also auto-generated. It exports `siteMetrics: SiteMetric[]` used by homepage Counter/Scoreboard. Regenerated by the same `docs-autogen` command.

## 5. Fumadocs MDX Components

All Fumadocs default components are available via `fumadocs-ui/mdx` (registered in `components/mdx.tsx`):

- `<Callout>` / `<Callout type="warn">` / `<Callout type="error">` — Callout boxes
- `<Tab>` / `<Tabs>` — Tabbed content sections
- `<Card>` / `<Cards>` — Card grids
- `<Steps>` / `<Step>` — Step-by-step guides
- `<Accordion>` / `<Accordions>` — Collapsible sections
- `<Mermaid chart="...">` — Custom Mermaid diagram component (defined in `components/mdx/mermaid.tsx`)

Use standard markdown code fences with `mermaid` language for diagrams — the `remarkMdxMermaid` plugin in `source.config.ts` transforms them automatically.

## 6. Interactive MDX Components

These are client-side components available in MDX content. All are registered in `components/mdx.tsx` via `getMDXComponents()`.

### SqlPlayground

`<SqlPlayground defaultQuery? parquetUrl? tableName? examples?>`

DuckDB-WASM sandbox. Lazy-initializes the WASM engine on first run. Defined in `components/mdx/sql-playground.tsx`.

| Prop           | Type                           | Description                                |
| -------------- | ------------------------------ | ------------------------------------------ |
| `defaultQuery` | `string`                       | Pre-filled SQL in the editor               |
| `parquetUrl`   | `string`                       | URL to a remote Parquet file to load       |
| `tableName`    | `string`                       | Table name for the loaded Parquet file     |
| `examples`     | `{label, sql, description?}[]` | One-click example queries shown as buttons |

The DuckDB-WASM singleton lives in `lib/duckdb.ts` — `getDb()` creates one shared instance, `runQuery()` executes SQL, and `registerParquet()` loads remote Parquet files into named tables with identifier validation.

### ObservablePlot

`<ObservablePlot options title? caption? className?>`

Generic Observable Plot wrapper. Pass any `Plot.plot()` options object. Client-only (dynamic import, SSR disabled). Defined in `components/mdx/observable-plot.tsx`.

### ShotChart

`<ShotChart data title? width? height?>`

Pre-configured dot plot with NBA court coordinates. Expects `{loc_x, loc_y, made?}[]`. Green (#00A651) / red (#C8102E) color coding for makes/misses. Default 500x470.

### GameFlow

`<GameFlow data title? width? height?>`

Score differential line chart. Expects `{period, time, score_diff}[]`. Area fill colored by lead/trail. NBA blue (#1D428A) stroke.

### PlayerCompare

`<PlayerCompare data title? width? height?>`

Grouped bar chart for comparing players across metrics. Faceted by `metric`, grouped by `player`. Expects `{player, metric, value}[]`.

### SeasonTrend

`<SeasonTrend data title? yLabel? width? height?>`

Multi-line chart for season-over-season trends. When `group` field is present, each group gets its own colored line. Expects `{season, value, group?}[]`.

### DistributionPlot

`<DistributionPlot data title? xLabel? bins? width? height?>`

Histogram for stat distributions. Stacked by `group` when present, otherwise NBA blue. Expects `{value, group?}[]`. Default 20 bins.

### HeatmapGrid

`<HeatmapGrid data title? width? height?>`

2D cell grid for zone efficiency heatmaps or calendars. YlOrRd sequential color scale. White text labels showing values rounded to 1 decimal. Expects `{x, y, value}[]`.

### Counter

`<Counter target duration? className?>`

Animated count-up with easeOutExpo curve, IntersectionObserver trigger (0.3 threshold), and `prefers-reduced-motion` support. Used on homepage scoreboard. Defined in `components/site/counter.tsx`.

## 7. Custom MDX Typography & Layout Components

All registered in `components/mdx.tsx` via `getMDXComponents()`:

| Component        | Props                     | Description                                   |
| ---------------- | ------------------------- | --------------------------------------------- |
| `<StatPill>`     | `label, value, note?`     | Single metric display in a bordered card      |
| `<StatGrid>`     | `columns={2\|3\|4}`       | Gap-separated grid wrapper for StatPills      |
| `<ScoutCard>`    | `title, label?, children` | Note card with Badge header                   |
| `<DataColumns>`  | `children`                | Two-column grid for side-by-side content      |
| `<CommandBlock>` | `command, label?`         | Terminal-style command with `$` prefix        |
| `<MetricRow>`    | `children`                | Inline flex metric strip with divider borders |
| `<Metric>`       | `label, value`            | Single inline metric (use inside MetricRow)   |
| `<InsightCard>`  | `title?, children`        | Note callout with primary left border         |
| `<WarningCard>`  | `title?, children`        | Warning callout with destructive left border  |
| `<CourtDivider>` | `label?`                  | Horizontal rule with centered Badge label     |

Note: `blockquote` is globally overridden to `TerminalQuote` (primary left border, muted background).

## 8. UI Component Library

### Badge (`components/ui/badge.tsx`)

6 CVA variants:

| Variant   | Style                                                |
| --------- | ---------------------------------------------------- |
| `default` | `border-border`, `text-muted-foreground`             |
| `primary` | `border-primary/30`, `text-primary`                  |
| `accent`  | `border-accent/30`, `text-accent`                    |
| `stat`    | `border-primary/40`, `bg-primary/10`, `text-primary` |
| `outline` | `border-border`, `text-foreground`                   |
| `muted`   | `border-border`, `bg-muted`, `text-muted-foreground` |

All badges are 0.65rem, font-semibold, uppercase, tracking-[0.2em].

### Button (`components/ui/button.tsx`)

4 variants x 4 sizes:

- **Variants**: `primary`, `secondary`, `outline`, `ghost`
- **Sizes**: `default` (h-9), `sm` (h-8, uppercase), `lg` (h-10), `icon` (size-9)
- Supports `asChild` prop for Radix Slot composition (e.g., wrapping `<Link>`)

### Other UI Components

- **Card** (`card.tsx`) — Surface container
- **Tabs** (`tabs.tsx`) — Radix-based tabbed UI
- **Skeleton** (`skeleton.tsx`) — Loading placeholder

## 9. Docs Chrome Components

Defined in `components/site/docs-shell.tsx` — context-aware UI chrome driven by `lib/site-config.ts`:

| Component                   | Description                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------- |
| `DocsPageHero`              | Page hero with breadcrumbs, section badges, stats, lead CTA, logo mark. Rendered on every docs page.  |
| `DocsContextRail`           | Related links grid + discovery panel with search prompts. Appended after MDX body.                    |
| `DocsGeneratedEntrySurface` | Entry surface for auto-generated pages. Shows generator info, stats, usage steps, and ownership note. |
| `DocsGeneratedScanSurface`  | TOC-driven scan surface that clusters h2 headings by table family. 8 page-key configs.                |
| `DocsGeneratedModules`      | Module cards grid for generated page companions.                                                      |
| `DocsNavBadge`              | Section/cue route pill displayed in the top navbar.                                                   |
| `DocsSidebarBanner`         | Context-aware sidebar header with section info, stats, and quick links.                               |
| `DocsSidebarFooter`         | Sidebar footer with badges, GitHub/PyPI shields, and search prompt.                                   |

All chrome components derive their content from `getSectionMeta(slug?)`, `getGeneratedPageFrame(slug?)`, and `getDocsContextRail(slug?)` in `lib/site-config.ts`.

## 10. Site Configuration

### `lib/site-config.ts`

Central configuration for all docs chrome. Key types:

```typescript
type SectionId =
  | "core"
  | "schema"
  | "data-dictionary"
  | "diagrams"
  | "endpoints"
  | "lineage"
  | "guides";

type SectionMeta = {
  id: SectionId;
  label: string;
  eyebrow: string;
  cue: string;
  blurb: string;
  hubHref: string;
  stats: SectionStat[];
  quickLinks: QuickLink[];
  prompts: SearchPrompt[];
};

type GeneratedPageFrameMeta = {
  eyebrow: string;
  title: string;
  description: string;
  stats: SiteMetric[];
  steps: GeneratedPageGuideStep[];
  generatorLabel: string;
  ownershipNote: string;
  regenerateCommand: string;
  modulesEyebrow: string;
  modulesTitle: string;
  modulesDescription: string;
  modules: GeneratedPageGuideCard[];
};
```

Helper functions:

| Function                        | Returns                          | Description                                            |
| ------------------------------- | -------------------------------- | ------------------------------------------------------ |
| `getSectionMeta(slug?)`         | `SectionMeta`                    | Resolves the current section from a docs slug          |
| `getGeneratedPageConfig(slug?)` | `GeneratedPageConfig \| null`    | Unified generated-page config accessor                 |
| `getGeneratedPageFrame(slug?)`  | `GeneratedPageFrameMeta \| null` | Frame config for auto-generated pages                  |
| `getDocsContextRail(slug?)`     | `DocsContextRailMeta`            | Related links and prompts for the generated context rail |

Exported data objects: `heroSignals`, `searchPrompts`, `docsSections`.

Site-wide constants: `siteOrigin` (`https://nbadb.w4w.dev`), `siteName`, `siteTitle`, `siteDescription`.

### `lib/site-metrics.generated.ts`

Auto-generated by `uv run nbadb docs-autogen`. DO NOT HAND-EDIT. Exports `siteMetrics: SiteMetric[]` used by homepage Counter/Scoreboard.

### `lib/duckdb.ts`

DuckDB-WASM singleton for the SQL playground:

- `getDb()` — Lazy-init shared `AsyncDuckDB` instance (jsDelivr CDN bundles)
- `runQuery(sql)` — Execute SQL, return `{columns, rows}`
- `registerParquet(tableName, url)` — Load remote Parquet into a named table (identifier-validated)

### `lib/use-zoom-pan.ts`

React hook for zoom/pan interactions on Mermaid diagrams. Returns transform state and event handlers.

### `lib/utils.ts`

- `cn()` — Tailwind class merge helper (`clsx` + `tailwind-merge`)
- `buildDocHref()` — Canonical `/docs/...` href builder from slug parts
- `getDocSlugFromHref()` — Parse a docs href back into slug parts when needed
- `getDocBreadcrumbs()` — Build breadcrumb trail from slug
- `humanizeSlug()` — Convert slug segments to human-readable labels

## 11. Admin Area

- **Route group**: `app/(admin)/admin/`
- **Auth**: `proxy.ts` guards admin requests, and `lib/admin/session.ts` holds the shared HMAC-signed session creation/validation helpers plus cookie constants and cookie helpers used by the login, logout, and proxy flows.
- Requires `ADMIN_PASSWORD` env var. Without it, page routes stay unavailable and admin API routes return a 503 misconfiguration response.
- **Matcher**: `/admin/:path*` and `/api/admin/:path*`
- **Unauthenticated behavior**: redirects to `/admin/login` (pages) or returns 401 (API routes)
- **Login/logout bypass**: `/admin/login`, `/api/admin/login`, `/api/admin/logout` remain public only when a password is configured; missing config never creates an implicit bypass
- **Metadata**: `robots: { index: false, follow: false }` on admin routes

### Admin Pages

| Page     | Description                                        |
| -------- | -------------------------------------------------- |
| Login    | Password-based login form                          |
| Pipeline | Pipeline monitoring dashboard with Recharts charts |

### Admin Components (13)

Located in `components/admin/`:

| Component               | Description                          |
| ----------------------- | ------------------------------------ |
| `admin-shell.tsx`       | Admin page layout shell              |
| `admin-nav.tsx`         | Admin navigation bar                 |
| `kpi-card.tsx`          | Key performance indicator card       |
| `sparkline-card.tsx`    | Metric card with inline sparkline    |
| `tracker-bar.tsx`       | Horizontal tracker/progress bar      |
| `chart-area.tsx`        | Recharts area chart wrapper          |
| `chart-bar.tsx`         | Recharts bar chart wrapper           |
| `chart-donut.tsx`       | Recharts donut/pie chart wrapper     |
| `bar-list.tsx`          | Horizontal bar list for ranked items |
| `content-freshness.tsx` | Content age/freshness display        |
| `freshness-heatmap.tsx` | Calendar heatmap for content age     |
| `status-dot.tsx`        | Colored status indicator dot         |
| `data-table.tsx`        | TanStack React Table data grid       |

## 12. Design System — `nba-*` CSS Namespace

Custom CSS classes in `app/global.css` (~1190 lines). These extend the Fumadocs `fd-*` design tokens with project-specific chrome.

### Token guardrails

- `app/global.css` has a top-level token stack:
  1. foundation tokens from Fumadocs/shadcn (`--background`, `--primary`, `--border`, etc.)
  2. docs semantic aliases (`--nba-*`, `--layer-*`, `--section-*`, `--chart-*`)
  3. component selectors (`.nba-*`)
- Repeated docs-only color mixes should be promoted into the semantic token layer before reuse in selectors.
- Keep dark-mode overrides in the token layer; avoid per-component `.dark` color forks unless a component truly needs a unique visual treatment.
- Section tokens `--section-core`, `--section-schema`, and `--section-diagrams` intentionally alias chart tokens so dark-mode updates stay in sync.
- Layer background tokens should stay derived from their layer color tokens in dark mode to reduce drift when palette values change.

### Layout Shells

- `nba-home-shell` — Landing page container
- `nba-docs-layout` — Docs layout wrapper
- `nba-docs-page` — Docs page container

All use `::before` gradient overlays and `isolation: isolate` for stacking context.

### Court Panel

Decorative court illustration on the homepage hero:

- `nba-court-panel` — Hero illustration container
- `nba-court-markings` — Court line group
- `nba-court-midline` — Half-court line
- `nba-court-circle` — Center circle
- `nba-court-key` — Paint/key area
- `nba-court-arc` — Three-point arc

### Typography

| Class                  | Style                                                       |
| ---------------------- | ----------------------------------------------------------- |
| `nba-kicker`           | 0.65rem, bold, uppercase, tracking-wide, primary color      |
| `nba-display`          | Heading font (IBM Plex Sans), tight tracking, balanced wrap |
| `nba-scoreboard-value` | Monospace, tabular-nums, tight line-height                  |
| `nba-metric-label`     | 0.65rem, bold, uppercase, muted-foreground                  |

### Reveal System

Intersection-triggered fade-up animations:

- `nba-reveal` — Base class: fade-up 500ms
- `nba-delay-1` — 80ms delay
- `nba-delay-2` — 160ms delay
- `nba-delay-3` — 240ms delay

### Surface Family

Shared box-shadow treatment applied to:

`nba-surface`, `nba-page-hero`, `nba-mdx-body`, `nba-sidebar-banner`, `nba-sidebar-footer`, `nba-related-card`, `nba-discovery-panel`

### Navigation

- `nba-nav-brand` — Brand mark in top nav
- `nba-nav-brand-mark` — Logo/icon element
- `nba-nav-command` — Command palette trigger
- `nba-nav-route` — Section/cue route pill

### Sidebar

- `nba-sidebar-banner` — Sidebar header with section info
- `nba-sidebar-stat` — Inline stat in sidebar
- `nba-sidebar-route-link` — Quick link in sidebar
- `nba-sidebar-footer` — Sidebar footer
- `nba-sidebar-prompt` — Search prompt in sidebar

### Mermaid / Visualization

- `nba-viz-shell` — Visualization container
- `nba-viz-toolbar` — Title/caption bar above visualization
- `nba-viz-status` — Status indicator
- `nba-zoom-controls` — Zoom in/out/reset buttons
- `nba-mermaid-shell` — Mermaid diagram container
- `nba-mermaid-viewport` — Scrollable/pannable viewport
- `nba-mermaid-canvas` — Inner canvas with transform

## 13. Development

```bash
cd docs
pnpm install     # Install dependencies
pnpm dev         # Start dev server (http://localhost:3000)
pnpm build       # Production build (catches errors)
pnpm format:check # Prettier verification
pnpm lint        # ESLint
pnpm format      # Prettier auto-fix
```

Node 22 is required (`engines.node` in `package.json`).

## 14. Regenerating Docs from Source

From project root:

```bash
uv run nbadb docs-autogen --docs-root docs/content/docs
```

Do not run that command from `docs/`. Using the same relative path from inside the docs app creates a stray duplicate tree under `docs/docs/content/docs` instead of updating the live content graph.

This runs generators from `src/nbadb/docs_gen/`:

- `ERDiagramGenerator` — ER diagrams from Pandera schemas
- `LineageGenerator` — Table/column lineage from transform dependencies
- `SchemaDocsGenerator` — Schema reference pages
- `DataDictionaryGenerator` — Field-level data dictionary
- `SiteMetricsGenerator` — Homepage scoreboard metrics (`site-metrics.generated.ts`)

## 15. Style Guidelines

- Use Fumadocs `fd-*` design tokens for colors/spacing (not raw Tailwind colors)
- Use `nba-*` classes for custom chrome components (see section 12)
- Prefer existing `--nba-*` semantic tokens in `app/global.css` before introducing a new `color-mix()` in a selector
- Use `var(--primary)` via `color-mix()` for any new theme-aware colors
- Mermaid diagrams: use `style` directives for color-coding sections
- Tables for structured data, Mermaid for relationships/flows
- Keep pages focused — one concept per page
- Use frontmatter `title` and `description` on every MDX page
- All animations must respect `prefers-reduced-motion` (global rule at end of `global.css`)
- OKLCH color space for all palette values (light and dark modes in `:root` / `.dark`)
- Prefer `border-border`, `text-muted-foreground`, `bg-card` tokens over raw color values
