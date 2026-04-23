---
title: Docs Telemetry and Health
tags:
  - kb
  - topics
  - docs
  - admin
  - telemetry
  - health
aliases:
  - Docs Health Model
  - Docs Telemetry Surface
kind: concept
status: active
updated: 2026-04-14
source_count: 11
---

# Docs Telemetry and Health

Use this note when you need the exact data model behind the docs admin dashboards and APIs: where content and pipeline health come from, how Umami plugs in, where profiling JSON is loaded from, and how the UI degrades when telemetry is missing.

## At a glance
| Lane | Primary source | Main consumers | Fallback shape |
| --- | --- | --- | --- |
| content audit | `docs/lib/admin/content-audit.ts` | `/admin`, `/admin/content`, `/admin/health`, `/api/admin/health` | empty page list and derived zero counts |
| pipeline summary | `docs/lib/admin/pipeline.ts` | `/admin`, `/admin/pipeline`, `/admin/health`, `/api/admin/health`, `/api/admin/pipeline-status` | stable empty `PipelineSummary` |
| Umami analytics | `docs/lib/admin/umami.ts` | `/admin`, `OverviewSparklines`, `/api/admin/umami` | `null` in loader, `503` in API, empty-state card in UI |
| profiling JSON | `readFirstJson()` plus `/admin/profiling` page loader | `/admin/profiling` | empty table-profile list and a regenerate hint |

## Content audit
- `getContentPages()` reads the live Fumadocs source graph through `source.getPages()` rather than a generated snapshot.
- Each page is normalized into `ContentPageMeta`: `title`, joined `slug`, `url`, section root, optional `description`, TOC depth, and filesystem `lastModified`.
- Section names are derived from the first slug segment, with `root` used for the docs landing page.
- File freshness is resolved from the content tree by trying `index.mdx` first and then the leaf `.mdx` path.
- `getContentAudit()` derives four operator-facing outputs: `pages`, `totalPages`, `missingDescription`, `shallowToc`, and `sectionCounts`.
- The current shallow-TOC heuristic is strict: any page with `tocDepth < 3` is flagged.

## Pipeline summary
- `getPipelineSummary()` loads the first JSON file that exists from this order:
  1. `lib/admin/pipeline-status.json`
  2. `lib/admin/pipeline-telemetry.generated.json`
- Missing files are skipped by `readFirstJson()`. Non-ENOENT read or parse failures throw immediately.
- When no pipeline JSON exists, the loader returns a stable empty summary rather than `null`.
- That empty summary keeps the dashboard contract intact: zeroed counts and totals, empty `runs`, `daily`, `slowEndpoints`, `failureHotspots`, and `recentErrors`, plus `windowDays = 14`.
- `overallPipelineStatus()` maps the summary into a runtime status:
  - no `lastRun` -> `abandoned`
  - any running count -> `running`
  - any failed count -> `failed`
  - otherwise -> `done`
- `pipelineToHealth()` then reduces pipeline runtime status into health severity:
  - `done` and `running` -> `healthy`
  - `failed` -> `degraded`
  - `abandoned` -> `unknown`
- `/api/admin/pipeline-status` returns the full summary plus `overallStatus`.

## Umami
- Umami is optional and is disabled unless both `UMAMI_API_TOKEN` and `NEXT_PUBLIC_UMAMI_WEBSITE_ID` are present.
- The adapter defaults `UMAMI_API_URL` to `https://api.umami.is/v1` and scopes requests to the configured website.
- Supported ranges are `24h`, `7d`, `30d`, and `90d`.
- Supported admin metrics are `stats`, `pageviews`, `pages`, and `referrers`.
- Requests use `next: { revalidate: 300 }`, so the admin analytics lane is cached for five minutes.
- Transport or upstream failures collapse to `null`; the loader does not throw.
- `/api/admin/umami` validates both metric and range, returns `400` for invalid query values, and returns `503` with `Analytics not configured or unavailable` when the adapter yields `null`.
- The overview page only asks for `getStats("7d")` when analytics is enabled, while `OverviewSparklines` fetches 7 day and 30 day pageview series from the admin API.

## Profiling JSON
- The profiling page is fed entirely from JSON, not live warehouse queries.
- It searches for the first available profile payload in this order:
  1. `table-profile.generated.json`
  2. `../table-profile.generated.json`
  3. `lib/admin/table-profile.generated.json`
- The loader returns `[]` when no profile JSON exists.
- An empty result does not fail the page. The UI renders a `No profiling data available` card and points operators at `uv run nbadb docs-autogen --docs-root docs/content/docs`.
- When profiles exist, the page groups them by `layer` and orders layers as `raw`, `staging`, `dimension`, `bridge`, `fact`, `aggregate`, `analytics`, then `other`.

## Admin health status model
- The machine-readable health contract is `HealthCheck` in `docs/lib/admin/types.ts`.
- It exposes:
  - `overall`
  - `subsystems.build`
  - `subsystems.search`
  - `subsystems.pipeline`
  - `subsystems.content`
  - `pageCount`
  - `lastBuild`
- Subsystem status values come from a shared enum: `healthy`, `degraded`, `down`, `unknown`.
- `/api/admin/health` computes subsystem details as follows:
  - build: always `healthy`, detail `${pages.length} pages indexed`
  - search: always `healthy`, detail `Fumadocs source search active`
  - pipeline: `pipelineToHealth(overallPipelineStatus(summary))`
  - content: `healthy` when at least one page exists, otherwise `degraded`
- API overall status is reduced with this precedence:
  1. any subsystem `down` -> `down`
  2. else any subsystem `degraded` -> `degraded`
  3. else all subsystems `healthy` -> `healthy`
  4. else -> `unknown`
- The HTML `/admin/health` page uses the same content and pipeline loaders but presents a slightly different operator view:
  - content and pipeline match the same core rules
  - search is shown as `healthy`
  - build is shown as `unknown` with `Runtime build health not verified`
  - overall page status only distinguishes `down`, `degraded`, and otherwise `healthy`
- `lastBuild` is currently emitted as `null` in the health API, so build freshness is not yet modeled as a first-class telemetry input.

## Fallback behavior
- `readFirstJson()` is the core JSON fallback primitive:
  - skips missing files
  - throws on malformed or unreadable JSON
  - returns `null` only when every candidate path is missing
- Content audit has no separate JSON dependency, so its failure mode is tied to the docs source graph itself.
- Pipeline summary never returns `null`; callers always receive a fully shaped `PipelineSummary`.
- Profiling returns an empty array and the page renders an instructional empty state.
- Umami returns `null` at the loader boundary, `503` at the API boundary, and a human-readable "Analytics not configured" card in the sparkline UI.
- The overview page also avoids unnecessary Umami fetches up front by checking env-based `analyticsEnabled` before requesting `getStats()`.

## Maintainer cues
- Prefer extending `docs/lib/admin/types.ts` before creating page-local telemetry shapes.
- Treat the JSON search order in `pipeline.ts` and the profiling page as part of the contract; changing those paths changes operational behavior.
- Treat `lastBuild` and build-status semantics as incomplete today. The API and HTML page intentionally diverge.

## Related notes
- [[wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/docs-generator-internals|Docs Generator Internals]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| content page inventory, mtime lookup, section derivation, audit outputs | `docs/lib/admin/content-audit.ts` | canonical content-audit loader |
| JSON fallback semantics for missing versus invalid files | `docs/lib/admin/files.ts` | shared JSON loader contract |
| pipeline file search order, empty summary, pipeline-to-health mapping | `docs/lib/admin/pipeline.ts` | canonical pipeline telemetry loader |
| telemetry and health type shapes | `docs/lib/admin/types.ts` | `PipelineSummary`, `HealthCheck`, Umami types |
| health API subsystem and overall reduction rules | `docs/app/api/admin/health/route.ts` | machine-readable health endpoint |
| pipeline-status API output shape | `docs/app/api/admin/pipeline-status/route.ts` | summary plus `overallStatus` |
| Umami env gating, range conversion, cache behavior, null-on-failure semantics | `docs/lib/admin/umami.ts` | analytics adapter |
| Umami API validation and `503` fallback | `docs/app/api/admin/umami/route.ts` | admin analytics API contract |
| profiling JSON search order, grouping, and empty-state behavior | `docs/app/(admin)/admin/profiling/page.tsx` | profiling page loader and UI |
| overview KPI composition and conditional Umami stats fetch | `docs/app/(admin)/admin/page.tsx` | top-level admin dashboard |
| sparkline fetch path and analytics-disabled empty state | `docs/app/(admin)/admin/overview-sparklines.tsx` | client-side traffic card behavior |
