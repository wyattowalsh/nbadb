---
title: Docs Admin Surface
tags:
  - kb
  - topics
  - docs
  - admin
  - frontend
aliases:
  - Docs Control Center
  - Docs Admin Area
kind: concept
status: active
updated: 2026-04-14
source_count: 20
---

# Docs Admin Surface

Use this note when you need the shape of the docs control plane: how `/admin` is gated, which routes exist, where each dashboard gets its data, and which components own charts versus tabular admin UI.

## Auth gate
- `docs/proxy.ts` guards both `/admin/:path*` and `/api/admin/:path*`.
- The only public admin paths are `/admin/login`, `/api/admin/login`, and `/api/admin/logout`.
- If `ADMIN_PASSWORD` is missing, page requests are redirected to `/admin/login` and admin API requests return `503` with a misconfiguration message.
- `docs/app/(admin)/admin/layout.tsx` is `force-dynamic`, sets `robots: noindex,nofollow`, and shows a warning banner when `ADMIN_PASSWORD` is absent.
- `docs/lib/admin/session.ts` stores auth in `nbadb-admin-session`, a signed `timestamp.mac` cookie with a 24 hour TTL. Validation rejects malformed, future-dated, or expired cookies.
- Session cookies are `httpOnly`, `sameSite: "lax"`, `path: "/"`, and `secure` only in production.
- `docs/app/api/admin/login/route.ts` compares passwords with HMAC-based constant-time digests, rate-limits failed logins to 5 bad attempts per 15 minutes, prefers trusted proxy IP headers on Cloudflare/Vercel/Fly, and falls back to a shared per-process bucket if client IP trust cannot be established.
- `docs/app/api/admin/logout/route.ts` clears the session cookie and returns `{ ok: true }`.

## Admin routes
| Route | Role | Main server/client pieces |
| --- | --- | --- |
| `/admin` | overview dashboard | `page.tsx`, `OverviewSparklines`, `KpiCard`, `TrackerBar`, `BarList`, `StatusDot` |
| `/admin/content` | docs content audit | `getContentAudit()`, `FilterableContentTable`, `ContentFreshness` |
| `/admin/pipeline` | extraction telemetry and hotspot view | `getPipelineSummary()`, `PipelineTabs`, `PipelineCharts`, `PipelineHistory` |
| `/admin/profiling` | generated table-profile browser | `readFirstJson()`, `ProfilingLayerTable` |
| `/admin/health` | site health and dependency snapshot | `getContentPages()`, `getPipelineSummary()`, `readPackageVersions()` |
| `/admin/login` | password entry | client form posting to `/api/admin/login` |

## Admin API routes
| Route | Output | Backing source |
| --- | --- | --- |
| `/api/admin/health` | `HealthCheck` JSON | content audit + pipeline summary |
| `/api/admin/content-meta` | content audit JSON | `getContentAudit()` |
| `/api/admin/pipeline-status` | pipeline summary + `overallStatus` | `getPipelineSummary()` |
| `/api/admin/umami` | stats, pageviews, top pages, or referrers | `docs/lib/admin/umami.ts` |
| `/api/admin/login` | sets session on success | `createAdminSessionToken()`, `setAdminSessionCookie()` |
| `/api/admin/logout` | clears session | `clearAdminSessionCookie()` |

## Dashboard components

### Shell and navigation
- `docs/components/admin/admin-shell.tsx` owns the desktop rail, mobile drawer, focus trap, escape-to-close behavior, and sign-out action.
- `docs/components/admin/admin-nav.tsx` defines the canonical nav: Overview, Content, Pipeline, Profiling, Health.

### Shared building blocks
| Component | Purpose |
| --- | --- |
| `KpiCard` | headline metric tiles with optional trend treatment |
| `SparklineCard` | KPI card plus small Recharts area sparkline |
| `TrackerBar` | status-strip timeline for runs/endpoints |
| `StatusDot` | subsystem or endpoint state badge with animated non-healthy pulse |
| `BarList` | ranked horizontal bar list for section counts or hotspots |
| `DataTable` | TanStack table with sorting and pagination |

### Page composition
- Overview combines content audit, pipeline summary, and optional Umami traffic stats.
- Content pairs a client-side filter bar with `ContentTable`, then adds section counts, freshness squares, and explicit missing-description rows.
- Pipeline mixes hero stats, extraction-state tracker, failure hotspot list, a `Current` chart tab, and a `History` tab.
- Profiling groups generated table profiles by layer and renders each group through `ProfilingLayerTable`.
- Health shows subsystem status rows plus a dependency-version table pulled from `package.json`.

## Health pages and telemetry model
- The HTML health page is `/admin/health`; the machine-readable health endpoint is `/api/admin/health`.
- Health status is synthesized from four subsystems: build, search, pipeline, and content.
- `docs/lib/admin/pipeline.ts` reads either `lib/admin/pipeline-status.json` or `lib/admin/pipeline-telemetry.generated.json`, merges partial payloads into a stable empty summary, and maps overall pipeline status to health severity.
- `docs/lib/admin/content-audit.ts` walks the Fumadocs source graph, derives section names from slug roots, and enriches each page with `description`, TOC depth, and filesystem mtime.
- `docs/lib/admin/umami.ts` is optional. Without `UMAMI_API_TOKEN` and `NEXT_PUBLIC_UMAMI_WEBSITE_ID`, overview sparklines and `/api/admin/umami` return fallback or `503` behavior rather than breaking the dashboard.

## Charts
- Admin charting is Recharts-based, matching `docs/AGENTS.md`.
- `ChartArea` wraps responsive area charts with gradient fill and lightweight grid/tooltip defaults.
- `ChartBar` wraps responsive bar charts and truncates long x-axis labels with tooltip-preserved full text.
- `ChartDonut` wraps a pie chart as the status-breakdown donut.
- `PipelineCharts` uses those wrappers for extraction volume, p95 endpoint latency, and run-status breakdown.
- `OverviewSparklines` uses `SparklineCard` to render 7 day and 30 day Umami pageview trends.
- The history view is not Recharts-based: `FreshnessHeatmap` colors endpoint freshness by hours since success, and the health-score list renders inline progress bars.
- Content freshness is also custom: `ContentFreshness` renders square swatches keyed by days since modification instead of a charting library.

## Maintainer cues
- Treat `docs/proxy.ts` plus `docs/lib/admin/session.ts` as the auth boundary. Route pages assume that guard already ran.
- Treat admin pages as operational UI, not public docs chrome; the route group is intentionally isolated from `/docs/**`.
- Prefer extending `docs/lib/admin/types.ts` before adding page-local telemetry shapes.
- When the dashboard has no generated telemetry or profiling JSON, pages degrade to empty-state cards instead of throwing.

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-component-registry|Docs Component Registry]]
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| docs admin route group, Recharts assignment, admin component inventory, proxy/session role | `docs/AGENTS.md` | canonical docs-app contract |
| matcher, public admin paths, missing-password behavior, page/API branching | `docs/proxy.ts` | auth gate and redirect/401/503 rules |
| session cookie name, TTL, HMAC token shape, cookie flags | `docs/lib/admin/session.ts` | shared auth/session helpers |
| login rate limiting, trusted proxy IP heuristics, constant-time password compare, cookie set on success | `docs/app/api/admin/login/route.ts` | login endpoint behavior |
| logout clears session cookie | `docs/app/api/admin/logout/route.ts` | logout endpoint behavior |
| admin metadata, noindex/nofollow, missing-password warning banner | `docs/app/(admin)/admin/layout.tsx` | route-group shell contract |
| login form behavior | `docs/app/(admin)/admin/login/page.tsx` | client-side entry page |
| overview route composition | `docs/app/(admin)/admin/page.tsx` | KPI, system health, tracker, section breakdown |
| overview traffic sparklines | `docs/app/(admin)/admin/overview-sparklines.tsx` | Umami-driven sparkline loader |
| content route composition | `docs/app/(admin)/admin/content/page.tsx` | content audit page shape |
| content filtering and table rendering | `docs/app/(admin)/admin/content/filterable-content-table.tsx`; `docs/app/(admin)/admin/content/content-table.tsx`; `docs/components/admin/data-table.tsx` | filter UX and TanStack table layer |
| pipeline route hero, KPIs, tabs, hotspots | `docs/app/(admin)/admin/pipeline/page.tsx` | main pipeline dashboard |
| current/history tab split | `docs/app/(admin)/admin/pipeline/pipeline-tabs.tsx` | tab routing inside pipeline page |
| pipeline chart composition | `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx`; `docs/components/admin/chart-area.tsx`; `docs/components/admin/chart-bar.tsx`; `docs/components/admin/chart-donut.tsx` | Recharts wrappers and usage |
| history heatmap and inline health-score bars | `docs/app/(admin)/admin/pipeline/pipeline-history.tsx`; `docs/components/admin/freshness-heatmap.tsx` | history-tab visualization layer |
| profiling route and generated JSON fallback | `docs/app/(admin)/admin/profiling/page.tsx`; `docs/app/(admin)/admin/profiling/profiling-layer-table.tsx` | profiling surface |
| health route HTML page | `docs/app/(admin)/admin/health/page.tsx` | subsystem summary and dependency table |
| health JSON, content-meta JSON, pipeline-status JSON, Umami JSON | `docs/app/api/admin/health/route.ts`; `docs/app/api/admin/content-meta/route.ts`; `docs/app/api/admin/pipeline-status/route.ts`; `docs/app/api/admin/umami/route.ts` | machine-facing admin endpoints |
| pipeline-summary loading and health mapping | `docs/lib/admin/pipeline.ts` | telemetry source and status normalization |
| content-audit loading and mtime enrichment | `docs/lib/admin/content-audit.ts` | content inventory source |
| Umami optional analytics integration | `docs/lib/admin/umami.ts` | external analytics adapter |
| admin shell/nav and shared cards, bars, dots, freshness widgets | `docs/components/admin/admin-shell.tsx`; `docs/components/admin/admin-nav.tsx`; `docs/components/admin/kpi-card.tsx`; `docs/components/admin/sparkline-card.tsx`; `docs/components/admin/tracker-bar.tsx`; `docs/components/admin/status-dot.tsx`; `docs/components/admin/content-freshness.tsx` | reusable admin UI primitives |
