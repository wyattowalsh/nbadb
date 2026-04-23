# Docs Admin Search Inventory

## Purpose
- Grouped internal extract manifest for the docs admin control-center shell, navigation, chart surface, admin health APIs, source-backed search, and seeded search trigger entry points.

## High-value paths

### Admin shell and navigation
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/layout.tsx` | Route-group layout that wraps admin pages in `AdminShell`, applies no-index metadata, and gates the surface on `ADMIN_PASSWORD`. |
| `docs/components/admin/admin-shell.tsx` | Control-center frame: desktop sidebar, mobile drawer, focus trap, escape handling, logout action, and main content container. |
| `docs/components/admin/admin-nav.tsx` | Canonical admin nav map for overview, content, pipeline, profiling, and health routes. |
| `docs/app/(admin)/admin/page.tsx` | Overview consumer that assembles health summary, section breakdown, pipeline tracker, and analytics-backed cards. |

### Admin charts and dashboard consumers
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` | Main pipeline dashboard composition for extraction volume, p95 latency, and status donut views. |
| `docs/app/(admin)/admin/overview-sparklines.tsx` | Overview-side sparkline consumer that fetches Umami pageview series from admin APIs. |
| `docs/components/admin/chart-area.tsx` | Recharts area wrapper used for time-series admin telemetry. |
| `docs/components/admin/chart-bar.tsx` | Recharts bar wrapper with label ellipsis behavior for long endpoint names. |
| `docs/components/admin/chart-donut.tsx` | Recharts donut wrapper for status distribution summaries. |
| `docs/components/admin/sparkline-card.tsx` | Compact KPI card with inline area sparkline for overview metrics. |

### Admin health APIs and data sources
| Path | Inventory role |
| --- | --- |
| `docs/app/api/admin/health/route.ts` | Top-level JSON health endpoint that combines content inventory and pipeline summary into build/search/pipeline/content subsystem statuses. |
| `docs/app/(admin)/admin/health/page.tsx` | Server-rendered health page that mirrors subsystem status, package versions, and dashboard KPIs. |
| `docs/app/api/admin/pipeline-status/route.ts` | Lightweight API surface for pipeline summary plus computed overall status. |
| `docs/app/api/admin/content-meta/route.ts` | JSON export of content-audit data used to inspect page counts, descriptions, and TOC depth. |
| `docs/app/api/admin/umami/route.ts` | Analytics proxy for stats, pageviews, top pages, and referrers with range validation and 503 fallback. |
| `docs/lib/admin/content-audit.ts` | Source-derived page inventory with section counts, missing-description detection, TOC shallowness, and file mtime lookup. |
| `docs/lib/admin/pipeline.ts` | Pipeline summary loader that reads generated JSON artifacts and maps pipeline state to health semantics. |

### Source search pipeline
| Path | Inventory role |
| --- | --- |
| `docs/app/api/search/route.ts` | Docs search API that wraps Fumadocs `createFromSource()` and expands shorthand queries before dispatch. |
| `docs/lib/source.ts` | Loader-backed Fumadocs source bridge built from generated docs/meta server exports. |
| `docs/lib/search-query.ts` | Query alias expansion layer for stat shorthand such as `ppg`, `rpg`, `apg`, `fg_pct`, and `bpm`. |
| `docs/source.config.ts` | MDX source definition for `content/docs`, which feeds the generated docs source consumed by search. |

### Search trigger components and entry points
| Path | Inventory role |
| --- | --- |
| `docs/components/site/search-trigger.tsx` | Thin client trigger that opens the Fumadocs dialog, resolves shortcut labels, locates the live input, and retries seeded prefill. |
| `docs/components/site/docs-nav.tsx` | Primary docs chrome entry point for open-search and seeded sidebar prompt actions. |
| `docs/components/site/docs-context-rail.tsx` | Context-rail search prompt surface that launches seeded queries from related-content panels. |
| `docs/app/(home)/layout.tsx` | Home-header search trigger that seeds a broad starter query for first-time navigation. |

## Notes
- The admin shell is split between route-level policy in `docs/app/(admin)/admin/layout.tsx` and client-side chrome in `docs/components/admin/admin-shell.tsx`; the shell owns drawer behavior, focus trapping, and logout transport.
- The admin chart layer is intentionally thin: `pipeline-charts.tsx` and `overview-sparklines.tsx` shape telemetry for shared Recharts wrappers instead of embedding bespoke chart logic per page.
- `docs/app/api/admin/health/route.ts` reports search as healthy when the Fumadocs source search path is active; build health is not runtime-probed there beyond page inventory availability.
- `docs/lib/admin/content-audit.ts` treats `source.getPages()` as the canonical content index, then augments it with on-disk modified dates from `content/docs`.
- `docs/lib/admin/pipeline.ts` reads the first available generated summary from `lib/admin/pipeline-status.json` or `lib/admin/pipeline-telemetry.generated.json`, so the health surface depends on prebuilt telemetry artifacts rather than direct pipeline execution.
- `docs/app/api/search/route.ts` is the source-search handoff point: it expands shorthand tokens through `expandSearchQuery()` and then delegates to `createFromSource(source, { language: "english" })`.
- `docs/components/site/search-trigger.tsx` uses DOM selectors plus staged retry delays to prefill the live search input after the dialog opens; seeded search entry points live in docs nav, the context rail, sidebar footer, and the home header.

## Planned wiki coverage
- `wiki/topics/docs-app-stack.md`
- `wiki/topics/docs-component-registry.md`
- `wiki/topics/docs-site-source-summary.md`
- future `wiki/topics/docs-admin-control-center.md`
- future `wiki/topics/docs-search-surface.md`

## Provenance
- `docs/app/(admin)/admin/layout.tsx`
- `docs/components/admin/admin-shell.tsx`
- `docs/components/admin/admin-nav.tsx`
- `docs/app/(admin)/admin/page.tsx`
- `docs/app/(admin)/admin/overview-sparklines.tsx`
- `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx`
- `docs/components/admin/chart-area.tsx`
- `docs/components/admin/chart-bar.tsx`
- `docs/components/admin/chart-donut.tsx`
- `docs/components/admin/sparkline-card.tsx`
- `docs/app/(admin)/admin/health/page.tsx`
- `docs/app/api/admin/health/route.ts`
- `docs/app/api/admin/pipeline-status/route.ts`
- `docs/app/api/admin/content-meta/route.ts`
- `docs/app/api/admin/umami/route.ts`
- `docs/lib/admin/content-audit.ts`
- `docs/lib/admin/pipeline.ts`
- `docs/app/api/search/route.ts`
- `docs/lib/source.ts`
- `docs/lib/search-query.ts`
- `docs/source.config.ts`
- `docs/components/site/search-trigger.tsx`
- `docs/components/site/docs-nav.tsx`
- `docs/components/site/docs-context-rail.tsx`
- `docs/app/(home)/layout.tsx`
