---
title: Docs Pipeline Dashboard
tags:
  - kb
  - topics
  - docs
  - admin
  - pipeline
  - telemetry
  - dashboard
aliases:
  - Admin Pipeline Dashboard
  - Pipeline Dashboard Semantics
kind: concept
status: active
updated: 2026-04-15
source_count: 11
---

# Docs Pipeline Dashboard

Use this note when you need the exact semantics of `/admin/pipeline`: which numbers are windowed versus cumulative, how the status badge is derived, why the History tab is synthetic, and how the charts reshape telemetry before rendering.

## Semantic map
| Surface | Primary inputs | What it actually represents |
| --- | --- | --- |
| hero badge and top KPI cards | `summary.counts`, `summary.totals`, `summary.lastRun`, `summary.generatedAt`, `summary.daily.at(-1)` | a mix of cumulative journal counts and windowed metric rollups |
| Current Extraction State | `summary.runs`, `summary.counts`, `summary.totals`, `summary.totalTables` | daily metric buckets projected into a run-like UI plus aggregate counters |
| Failure Hotspots | `summary.failureHotspots` | grouped failed or abandoned journal rows, not a live incident list |
| Current tab | `summary.daily`, `summary.counts`, `summary.slowEndpoints` | the main observability view: throughput, latency, and status mix |
| History tab | `summary.slowEndpoints`, `summary.generatedAt` | a synthetic freshness and endpoint-health snapshot, not long-range historical buckets |

## KPI derivations
- `getPipelineSummary()` loads `lib/admin/pipeline-status.json` first and falls back to `lib/admin/pipeline-telemetry.generated.json`, then merges the payload onto a stable empty summary.
- `Failed now`, `Running now`, and `Abandoned` come straight from `summary.counts`, which are built by `SELECT status, COUNT(*) FROM _extraction_journal GROUP BY status`.
- Those count KPIs are therefore journal-row counts, not distinct endpoints, not distinct runs, and not filtered by `windowDays`.
- `Rows (Nd)`, `Avg latency`, and `p95 latency` come from `summary.totals`, which are built only from the recent `daily` buckets in `_pipeline_metrics`.
- `summary.totals.p95DurationMs` is not a global p95 across all rows. It is copied from the first `slowEndpoints` item after sorting endpoints by p95 latency.
- `Latest Bucket` is `summary.daily.at(-1)` after the SQL rollups are re-sorted ascending by date.
- The `Current Extraction State` badge labeled `metric rows` is `summary.totals.runs`, which is the sum of `daily.runCount` across the telemetry window.
- The tracker bar does not render raw extraction attempts. `summary.runs` is built from daily buckets, and each bucket is marked `failed` when `errorCount > 0`, otherwise `done`.
- `Endpoint states` is `done + failed + running + abandoned`, so it inherits the same journal-row semantics as the top count KPIs.
- `Error rate` is `(summary.totals.errorCount / summary.totals.runs) * 100` with a zero guard.
- `Total tables` is the count of rows in `_pipeline_metadata`.
- `Staging metadata` is the percentage of `stg_*` rows in `_pipeline_metadata` whose `last_updated` is non-null.

## Status labels
| Runtime status | Rule | UI label |
| --- | --- | --- |
| `abandoned` | no `lastRun` | `No data` |
| `running` | any `summary.counts.running > 0` | `Running now` |
| `failed` | otherwise any `summary.counts.failed > 0` | `Errors detected` |
| `done` | otherwise | `Healthy` |

- Status precedence is `running` before `failed`, then `done`, with `abandoned` as the no-data fallback.
- Because `summary.counts.failed` is journal-wide, the page can stay on `Errors detected` long after the latest daily bucket is clean, as long as failed rows remain in `_extraction_journal`.

## Failure hotspots
- `failureHotspots` is built from `_extraction_journal`, filtered to `status IN ('failed', 'abandoned')`, grouped by `(endpoint, status)`, and ordered by `failure_count DESC, last_seen DESC, endpoint ASC`.
- The bar list uses `count` only. The detail lane shows just the first three grouped rows, plus `sampleError` when one exists.
- Hotspots are cumulative inside the retained journal. They are not bounded by the telemetry window and they are not limited to currently unresolved failures.
- `recentErrors` is a separate lane of recent failed or abandoned journal lines and can still render even when the chart region is empty.

## Current vs History
- The tab split is purely presentational: `Current` renders `PipelineCharts`; `History` renders `PipelineHistory`.
- `Current` is the real observability tab: extraction volume comes from `daily`, p95 endpoint latency comes from the top six `slowEndpoints`, and the donut breakdown comes from non-zero `counts`.
- `History` is not backed by a second time-series store. It is derived only from `slowEndpoints` plus `generatedAt`.
- `History` renders only when `summary.slowEndpoints.length > 0`; otherwise it shows an empty-state message even if `daily` or `failureHotspots` exists.
- The history tab should be read as an endpoint-age and endpoint-health interpretation of the current telemetry snapshot, not as historical trend reconstruction.

## Freshness and health-score synthesis
- The reference clock is `summary.generatedAt`, not browser time. Freshness ages freeze at export time.
- Each freshness entry is shaped from a slow endpoint as `{ endpoint, layer: "telemetry", lastSuccess: lastRun, hoursSinceSuccess }`.
- `hoursSinceSuccess` is `max(0, generatedAt - lastRun)` in hours. Missing `generatedAt` or missing `lastRun` collapses the age to `null`.
- Heatmap bands are `<24h` green, `24-72h` amber, `3-7d` orange, `>7d` red, and `null` muted `never`.
- History KPI cards are synthesized from those arrays: `Healthy` counts `healthScores.status === "healthy"`, `Degraded` counts `healthScores.status === "degraded"`, `Stale (>7d)` counts `hoursSinceSuccess > 168`, and `Never Succeeded` counts `hoursSinceSuccess === null`.
- Health score formula is `max(0, round(100 - errorRate * 100))`. Since `errorRate` is already a percentage, the score is effectively `100 - error percentage points`.
- Health score status thresholds are `healthy` at `score >= 85`, `degraded` at `score >= 60`, and `unhealthy` otherwise.
- The inline progress bar colors use different boundaries: green at `>=80`, amber at `>=50`, red otherwise.
- That means the status dot and the bar fill can disagree around the 50 to 59 and 80 to 84 ranges.

## Chart shaping
- The chart and tab region appears whenever at least one of `daily`, `slowEndpoints`, or `failureHotspots` is non-empty.
- `PipelineCharts` reshapes the telemetry before plotting: area-chart x labels use `bucket.label.slice(5)`, effectively `MM-DD`; latency bars split camel-case endpoint names into spaced labels; and the donut drops zero-value statuses before rendering.
- The Recharts wrappers standardize responsive sizing, lightweight grid lines, compact tooltips, and label handling.
- `ChartArea` adds a gradient fill under the line.
- `ChartBar` truncates long x labels with ellipsis but preserves the full string in a `<title>` tooltip.
- `ChartDonut` uses the raw status names and the page-level color map: `done` primary, `failed` destructive, `running` accent, `abandoned` muted.
- The History tab intentionally does not use Recharts. The freshness view is a grouped square heatmap, and the score view is rendered as inline progress bars.

## Maintainer cues
- Treat `summary.counts` and `failureHotspots` as journal-derived operational state, and `daily` plus `totals` as window-scoped metric rollups.
- Treat `summary.runs` as compatibility-shaped daily buckets, not one row per extraction attempt.
- If operators read the History tab as long-term history, clarify that it is a synthetic endpoint freshness layer over the current snapshot.

## Related notes
- [[wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[wiki/topics/docs-telemetry-health|Docs Telemetry and Health]]
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| loader fallback order and empty-summary merge | `docs/lib/admin/pipeline.ts` | canonical dashboard summary loader |
| status precedence and badge label mapping | `docs/lib/admin/pipeline.ts`; `docs/app/(admin)/admin/pipeline/page.tsx` | runtime status plus page-local label copy |
| hero cards, KPI cards, latest bucket, current-state cards, telemetry empty state | `docs/app/(admin)/admin/pipeline/page.tsx` | main pipeline dashboard composition |
| current/history tab split and history empty state | `docs/app/(admin)/admin/pipeline/pipeline-tabs.tsx` | tab routing semantics |
| current-tab reshaping for area, bar, and donut charts | `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` | chart input shaping layer |
| history KPI derivation, health-score sorting, stale and never counts | `docs/app/(admin)/admin/pipeline/pipeline-history.tsx` | synthetic history presentation |
| freshness band thresholds and tooltip semantics | `docs/components/admin/freshness-heatmap.tsx` | history heatmap rendering rules |
| Recharts wrapper behavior for area, bar, and donut charts | `docs/components/admin/chart-area.tsx`; `docs/components/admin/chart-bar.tsx`; `docs/components/admin/chart-donut.tsx` | shared admin chart wrapper rules |
| telemetry type contracts | `docs/lib/admin/types.ts` | `PipelineSummary`, rollups, endpoint telemetry, hotspot types |
| journal counts, staging coverage, daily rollups, slow-endpoint ranking, hotspot grouping, totals synthesis | `src/nbadb/cli/commands/status.py` | upstream telemetry export logic for `journal-summary` |
| telemetry JSON contract expectations | `tests/unit/cli/test_info_commands.py` | confirms admin-facing fields and populated example behavior |
