# Docs Telemetry Inventory

## Purpose
- Grouped internal extract manifest for the docs telemetry and status surface: content audit, generated pipeline summaries, optional Umami analytics, profiling JSON ingestion, admin health routes, and the overview and control-center pages that consume those signals.

## High-value paths

### Content audit and source-backed inventory
| Path | Inventory role |
| --- | --- |
| `docs/lib/admin/content-audit.ts` | Canonical content telemetry loader that reads the live Fumadocs source graph, resolves `lastModified` from `content/docs`, and derives `missingDescription`, `shallowToc`, and `sectionCounts`. |
| `docs/app/api/admin/content-meta/route.ts` | Machine-readable export of the content-audit payload for page inventory and docs-quality inspection. |
| `docs/app/(admin)/admin/content/page.tsx` | Admin content page consumer for the source-backed audit outputs. |
| `docs/app/docs/{catch-all}/page.tsx` | Docs page surface that reuses `getPageLastModified()` from the content-audit module for per-page freshness metadata. |

### Pipeline summary and telemetry rollups
| Path | Inventory role |
| --- | --- |
| `docs/lib/admin/pipeline.ts` | Canonical pipeline telemetry loader; reads `pipeline-status.json` or `pipeline-telemetry.generated.json`, merges into a stable `PipelineSummary`, and maps runtime status to health semantics. |
| `docs/lib/admin/files.ts` | Shared JSON fallback primitive used by pipeline and profiling loaders; skips missing files, throws on malformed JSON, and returns `null` only when every candidate path is absent. |
| `docs/app/api/admin/pipeline-status/route.ts` | JSON status surface that returns the full pipeline summary plus computed `overallStatus`. |
| `docs/app/(admin)/admin/pipeline/page.tsx` | Main pipeline telemetry consumer for KPI cards, failure hotspots, telemetry freshness, and status storytelling in the admin dashboard. |
| `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` | Chart composition layer for time-series throughput, latency, and status-distribution views built from `PipelineSummary`. |

### Umami integration and analytics gating
| Path | Inventory role |
| --- | --- |
| `docs/lib/admin/umami.ts` | Optional Umami adapter gated by `UMAMI_API_TOKEN` and `NEXT_PUBLIC_UMAMI_WEBSITE_ID`; converts date ranges, scopes requests to the configured website, applies five-minute revalidation, and collapses failures to `null`. |
| `docs/app/api/admin/umami/route.ts` | Admin analytics API that validates metric and range, proxies supported Umami reads, and returns `503` when analytics is unconfigured or unavailable. |
| `docs/app/(admin)/admin/overview-sparklines.tsx` | Client-side sparkline consumer that fetches `pageviews` series from the admin API and renders an explicit analytics-disabled empty state. |
| `docs/app/(admin)/admin/page.tsx` | Overview page that conditionally asks Umami for 7 day stats only when analytics is enabled, then folds that data into KPI cards. |

### Profiling JSON and generated table stats
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/profiling/page.tsx` | Profiling page loader and UI; searches three candidate JSON locations, returns `[]` when profiles are missing, groups tables by layer, and renders the regenerate hint. |
| `docs/lib/admin/files.ts` | Shared JSON search helper used by the profiling page to distinguish missing files from broken JSON. |
| `docs/lib/admin/types.ts` | Defines the `TableProfile` and `ColumnProfile` contract consumed by the profiling page. |
| `src/nbadb/docs_gen/table_profile.py` | Generator-side source of the table-profile JSON artifact that the docs profiling surface expects to read. |

### Admin health routes and status contracts
| Path | Inventory role |
| --- | --- |
| `docs/app/api/admin/health/route.ts` | Primary machine-readable health endpoint; combines content inventory and pipeline summary into build, search, pipeline, and content subsystem statuses plus overall health. |
| `docs/app/(admin)/admin/health/page.tsx` | Human-facing health page that mirrors the same core telemetry lanes but presents build as runtime-unverified and adds package-version inspection. |
| `docs/lib/admin/types.ts` | Shared contract for `HealthCheck`, `SubsystemStatus`, `PipelineSummary`, Umami payloads, and profiling records. |
| `docs/components/admin/status-dot.tsx` | Shared visual status primitive used to render subsystem health and other telemetry-derived states in the admin UI. |

### Telemetry and status consumers
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/page.tsx` | Top-level control-center surface that combines content audit, pipeline summary, and optional Umami stats into KPI cards, health summary, tracker bars, and section breakdowns. |
| `docs/components/admin/admin-nav.tsx` | Canonical nav surface advertising the telemetry-bearing routes: overview, content, pipeline, profiling, and health. |
| `docs/components/admin/kpi-card.tsx` | Shared KPI primitive for compact telemetry totals across overview, health, pipeline, and profiling pages. |
| `docs/components/admin/tracker-bar.tsx` | Shared run-status strip used to render pipeline and endpoint state summaries. |
| `docs/components/admin/bar-list.tsx` | Ranked-list primitive for section counts, failure hotspots, and other telemetry distributions. |
| `docs/components/admin/chart-area.tsx` | Shared time-series chart wrapper used for admin telemetry plots. |
| `docs/components/admin/chart-bar.tsx` | Shared horizontal or categorical chart wrapper for endpoint and section breakdowns. |
| `docs/components/admin/chart-donut.tsx` | Shared status-distribution chart wrapper used by pipeline telemetry views. |
| `docs/components/admin/sparkline-card.tsx` | Compact inline trend card used by the overview analytics surface. |

## Notes
- The docs telemetry surface is intentionally split between source-backed signals and generated JSON artifacts. Content audit reads the live Fumadocs source graph directly, while pipeline and profiling depend on prebuilt JSON snapshots.
- `docs/lib/admin/files.ts` is the contract boundary for JSON-backed telemetry. Missing files are treated as expected fallback cases, but malformed or unreadable JSON is considered a hard failure.
- Pipeline telemetry always returns a fully shaped `PipelineSummary`; callers do not need to handle `null`. The empty state is encoded as zeroed totals, empty arrays, `windowDays = 14`, and `lastRun = null`.
- Pipeline health semantics are intentionally lossy: `done` and `running` are treated as `healthy`, `failed` becomes `degraded`, and `abandoned` becomes `unknown`.
- Umami is optional by design. Loader failures degrade to `null`, the API translates that to `503`, and the overview UI shows operator-facing empty states instead of throwing.
- The overview page short-circuits the initial server-side Umami request when analytics env vars are absent, while `OverviewSparklines` still owns the client fetches for 7 day and 30 day pageview trends when enabled.
- Profiling is JSON-only and does not query the warehouse at request time. The page groups `TableProfile` rows by `layer` and treats missing artifacts as a non-fatal operator condition.
- The machine-readable health API and the HTML health page intentionally diverge on build status today: the API reports build as `healthy` with a page-count detail, while the page labels build as `unknown` and explicitly says runtime build health is not verified.
- `lastBuild` remains `null` in the health API, so build freshness is not yet modeled as a first-class telemetry signal.
- The admin control center surfaces telemetry through a small set of reusable primitives (`KpiCard`, `StatusDot`, `TrackerBar`, chart wrappers) rather than page-local visualization logic.

## Planned wiki coverage
- `wiki/topics/docs-telemetry-health.md`
- `wiki/topics/docs-admin-surface.md`
- `wiki/topics/docs-autogen.md`
- future `wiki/topics/docs-pipeline-dashboard.md`
- future `wiki/topics/docs-content-audit.md`

## Provenance
- `docs/lib/admin/content-audit.ts`
- `docs/lib/admin/pipeline.ts`
- `docs/lib/admin/umami.ts`
- `docs/lib/admin/files.ts`
- `docs/lib/admin/types.ts`
- `docs/app/api/admin/content-meta/route.ts`
- `docs/app/api/admin/health/route.ts`
- `docs/app/api/admin/pipeline-status/route.ts`
- `docs/app/api/admin/umami/route.ts`
- `docs/app/(admin)/admin/page.tsx`
- `docs/app/(admin)/admin/content/page.tsx`
- `docs/app/(admin)/admin/health/page.tsx`
- `docs/app/(admin)/admin/pipeline/page.tsx`
- `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx`
- `docs/app/(admin)/admin/profiling/page.tsx`
- `docs/app/(admin)/admin/overview-sparklines.tsx`
- `docs/app/docs/{catch-all}/page.tsx`
- `docs/components/admin/admin-nav.tsx`
- `docs/components/admin/kpi-card.tsx`
- `docs/components/admin/status-dot.tsx`
- `docs/components/admin/tracker-bar.tsx`
- `docs/components/admin/bar-list.tsx`
- `docs/components/admin/chart-area.tsx`
- `docs/components/admin/chart-bar.tsx`
- `docs/components/admin/chart-donut.tsx`
- `docs/components/admin/sparkline-card.tsx`
- `src/nbadb/docs_gen/table_profile.py`
