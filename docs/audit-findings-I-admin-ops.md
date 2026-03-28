# Audit I: Admin Operational Dashboards

**Auditor:** Claude Opus 4
**Date:** 2026-03-28
**Method:** Full source code review of all admin components, API routes, data modules, middleware, and CSS + live page capture (partial, server went down mid-session)
**Files reviewed:** 35 source files across `app/(admin)/`, `components/admin/`, `lib/admin/`, `app/api/admin/`, and `middleware.ts`

---

## /admin (Main Dashboard)

### KPI Cards

- **5-column KPI row** (Total pages, Missing descriptions, Shallow TOC, Visitors 7d, Pageviews 7d) uses `lg:grid-cols-5`. On medium screens (`sm:grid-cols-2`) the 5th card wraps awkwardly to a standalone row.
- Visitor/pageview KPIs show a dash (`"---"`) when Umami is not configured, which is the expected state for local dev. This is acceptable but the dash character is ambiguous -- it could mean "zero" or "unavailable."
- `KpiCard` supports a `trend` prop (with `TrendingUp`/`TrendingDown` icons) but **no card on the overview page uses it**. The trend capability is dead weight on this page.
- KPI values use `nba-scoreboard-value` (monospace, tabular-nums) which is good for numeric readability.

### Charts / Sparklines

- `OverviewSparklines` is a client component that fetches from `/api/admin/umami?metric=pageviews`. When Umami is not configured it shows a clear fallback: "Analytics not configured. Set `UMAMI_API_TOKEN` to enable traffic sparklines." -- good empty state.
- Loading state uses `<Skeleton className="h-32" />` (two skeletons in a 2-col grid). Good.
- The sparkline gradient IDs use `id={`spark-${label}`}` which works because labels are unique per card, but if two SparklineCards had the same label, SVG gradient definitions would collide. Low risk but technically fragile.
- SparklineCard has `isAnimationActive={false}` which is correct for small sparklines.

### Data States

- **No pipeline data:** Shows "No pipeline run data available" in the Pipeline Runs card. Clear.
- **No health data:** Shows "Health data unavailable" text. Clear.
- **Content data** is synchronous (`getContentAudit()`) and always available since it reads from the Fumadocs source. This never fails.
- The main page fetches from its own API routes (`/api/admin/health`, `/api/admin/pipeline-status`, `/api/admin/umami`) using `process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"` as base URL. **DEFECT D1:** This is a server component making HTTP requests to itself. During SSR the fetch goes through the network stack to localhost, which (a) adds unnecessary latency, (b) can fail if the server is still starting up, and (c) is redundant since the data functions (`getPipelineSummary`, `getContentAudit`) are already available as direct imports on the server.

### System Health Card

- Uses `StatusDot` with animated ping effect for each subsystem. The ping animation runs perpetually on all dots, even healthy ones. **Enhancement E1:** Consider only animating the ping on non-healthy statuses to reduce visual noise and draw attention to problems.

---

## /admin/content

### Content Table

- Uses TanStack React Table v8 with `DataTable` generic wrapper. **Sorting works** on all 4 columns (Title, Section, Description, TOC depth) via click-to-sort headers with `ArrowUp`/`ArrowDown`/`ArrowUpDown` indicators.
- Pagination is set to 20 rows per page (`initialState: { pagination: { pageSize: 20 } }`). With 49 pages this means 3 pages. Page controls (Prev/Next) appear when `pageCount > 1`.
- **DEFECT D2:** The Description column renders with `className="max-w-xs truncate"` but `<td>` elements inside a `<table>` do not truncate without `table-layout: fixed` or explicit width. The truncation CSS is likely ignored, causing long descriptions to stretch the column. Need `max-w-0 w-full` or `table-layout: fixed` on the table.
- **DEFECT D3:** No search/filter functionality on the content table. An operator looking for a specific page must visually scan or sort. A text filter input would significantly improve usability.
- Title column links to the actual docs page (`href={info.row.original.url}`), which is useful for quick navigation.
- Section column uses a small badge (`text-[0.65rem]`), which is nicely compact.
- "Missing" descriptions show in `text-destructive/70` with "Missing" text, providing clear visual signal.

### Freshness Display

- **DEFECT D4:** Content freshness data is **entirely synthetic**. The code computes `daysOld: Math.min((p.slug.length + i + 1) * 3, 119)` -- a deterministic placeholder based on slug length and index. The comment says "Deterministic placeholder until git/file timestamps are wired into the audit." This means the freshness heatmap is **misleading** -- it shows color-coded age data that has no relationship to actual content age.
- The `ContentFreshness` component itself is well-built: proper color legend, tooltip on hover, responsive flex-wrap grid of 6x6px cells.
- The `ageColor()` function has sensible thresholds: <14d, 14-30d, 30-60d, 60-90d, >90d.
- `lastModified` in `ContentPageMeta` is always `null` -- the content-audit module never populates it.

### KPI Cards

- 4-column KPI row (`lg:grid-cols-4`) is well-proportioned. No orphan issues since 4 divides evenly.

### Missing Descriptions Card

- Conditional render: only shows when `audit.missingDescription.length > 0`. Good.
- Each item is a clickable link to the docs page. Good for quick remediation.

---

## /admin/pipeline

### Pipeline Hero Card

- Large gradient hero card with status summary and metadata grid. The gradient uses `color-mix(in_oklch, ...)` which is modern CSS -- good browser support in 2026 but worth noting.
- Status label mapping (`done` -> "Healthy", `failed` -> "Errors detected", `running` -> "Running now", `abandoned` -> "No data") is clear and operator-friendly.
- `formatDateTime` uses `Intl.DateTimeFormat` with graceful fallback. Good.

### Pipeline KPI Row

- **6-column KPI row** (`xl:grid-cols-6`) with: Failed now, Running now, Abandoned, Rows (window), Avg latency, p95 latency. On smaller screens: `sm:grid-cols-2`. With 6 items on sm this creates 3 rows of 2 -- acceptable.
- **Enhancement E2:** The latency KPIs show raw milliseconds (e.g., "0ms") with no unit formatting for large values. Consider humanizing: "1.2s" instead of "1200ms".

### Pipeline Charts (`PipelineCharts`)

- Three charts: Extraction Volume (area), p95 Endpoint Latency (bar), Status Breakdown (donut).
- **Area chart** uses `ChartArea` wrapping Recharts `AreaChart` with gradient fill, grid, axes, tooltip. Good configuration. The `xKey` labels are sliced with `bucket.label.slice(5)` which removes the year prefix (e.g., "2026-" -> "03-28"). This is fragile if label format changes.
- **Bar chart** truncates endpoint names to 16 chars and inserts spaces before capitals. **DEFECT D5:** The regex `item.endpoint.replace(/([A-Z])/g, " $1").trim().slice(0, 16)` inserts a space before every capital, then trims. For an endpoint like "CommonPlayerInfo" this produces "Common Player In" (truncated mid-word). The truncation should be smarter or use an ellipsis.
- **Donut chart** filters out zero-value statuses (`filter(([, v]) => v > 0)`). Good -- avoids rendering empty slices. However, **DEFECT D6:** when all counts are zero (no pipeline data), the donut renders nothing and the card shows an empty centered space. The parent `PipelineCharts` component is only rendered when `hasTelemetry` is true, but `hasTelemetry` checks `daily.length > 0 || slowEndpoints.length > 0 || failureHotspots.length > 0` -- it's possible for counts to be all-zero while daily has data, resulting in an empty donut.
- **DEFECT D7:** The `ChartArea` component uses `id={`area-${yKey}`}` for the SVG gradient definition. If two area charts with the same `yKey` exist on the same page, they will share/overwrite the gradient. Currently safe since only one area chart exists, but fragile for future use.

### Tab Navigation (`PipelineTabs`)

- **DEFECT D8:** `PipelineTabs` component exists and is fully implemented with "Current" and "History" tabs, but **it is never used**. The pipeline page (`page.tsx`) renders `PipelineCharts` directly instead of using `PipelineTabs`. The tab switching functionality is dead code.
- The History tab placeholder ("No history data available") is good fallback text.

### History View (`PipelineHistory`)

- Well-structured with KPI row (Healthy/Degraded/Stale/Never), freshness heatmap, and health scores list.
- `FreshnessHeatmap` groups data by layer and renders color-coded cells with tooltips. The tooltip computation (`cellTooltip`) correctly handles null (never succeeded) and provides human-readable age strings.
- Health scores list uses progress bars with color thresholds (>=80 green, >=50 amber, <50 red). Good visual encoding.
- **DEFECT D9:** `PipelineHistory` accepts a `trends` prop but **never uses it**. The `trends` data (endpoint run-date trend lines) is declared in the type but the component body only destructures `{ freshness, healthScores }`.

### Failure Hotspots

- BarList + detail cards for top 3 failures. Shows endpoint name, status badge, and sample error message. Good operational signal.
- "No error message captured" fallback when `sampleError` is null. Appropriate.

### Slowest Endpoints

- BarList with p95 latency values. Shows "Top N" count in badge. Good.
- **Enhancement E3:** No unit label on the BarList values. An operator sees "1200" but has to infer these are milliseconds from context.

### Telemetry Window

- 4-cell grid showing Metric rows, Rows extracted, Observed errors, Staging metadata%. Good summary.

### Recent Errors

- Conditional render for recent error lines in monospace. Good for debugging.
- Uses `index` + string prefix as key: `key={`${index}-${errorLine.slice(0, 24)}`}`. Acceptable since this list is static per render.

### No-Data State

- When `hasTelemetry` is false, shows a centered card with the CLI command to generate data. Good operator guidance.

---

## /admin/profiling

### Table Profiling

- Reads from `table-profile.generated.json` with 3 fallback paths. Clean loading pattern.
- **Empty state** is well-handled: shows "No profiling data available" with the generation command.
- When data exists, shows 3 KPI cards (Tables, Total Rows, Total Columns) and then one card per data layer (raw, staging, dimension, bridge, fact, aggregate, analytics, other).
- Layer ordering is hardcoded in `layerOrder` array. Layers not in the array would sort by default (end of list) due to `indexOf` returning -1. **DEFECT D10:** Unknown layers get `indexOf` = -1 and sort to the top (before "raw"). Should use a fallback like `layerOrder.indexOf(a[0]) ?? 999`.
- Tables within each layer card are rendered in a native HTML `<table>` (not TanStack). **DEFECT D11:** No sorting capability on profiling tables. If a layer has many tables, the operator cannot sort by row count or column count to find outliers.
- **DEFECT D12:** No pagination on profiling tables. If a layer has 100+ tables, the entire list renders in a single card with no scroll constraint. The card will be extremely tall.
- Table styling is consistent with the rest of the admin panel (monospace values, tabular-nums, hover states).

---

## /admin/health

### Site Health

- Shows overall health badge in the header row.
- 4 KPI cards: Total pages, Missing descriptions, Pipeline tables, Staging coverage.
- Subsystem status cards use `StatusDot` with ping animation (same as overview).
- **DEFECT D13:** Dependency versions are **hardcoded** in the component:
  ```ts
  { name: "next", version: "16.2.0" },
  { name: "fumadocs-core", version: "16.6.17" },
  ```
  These will drift from actual installed versions. Should read from `package.json` or use build-time generation.
- **DEFECT D14:** The `Build` subsystem status is always hardcoded as `"healthy"` with detail `"Next.js 16.2 + Fumadocs 16.6"`. There is no actual build health check (e.g., checking if the last build succeeded or if there are build errors).
- **DEFECT D15:** The `Search` subsystem status is always hardcoded as `"healthy"` with detail `"Orama search active"`. There is no actual verification that the search index exists or is functional.
- **Enhancement E4:** The health page has no refresh/recheck button. An operator must reload the entire page to get updated health data.

---

## Authentication & Security

### Login Page

- Clean centered form with password input, error display, loading state. Accessible (has `label`, `htmlFor`, `autoFocus`, `required`).
- Uses `fetch` POST to `/api/admin/login`, then `router.push("/admin")` + `router.refresh()` on success.

### Middleware

- HMAC-SHA256 session cookie with timing-safe comparison. Session expires after 24 hours.
- **DEFECT D16:** When `ADMIN_PASSWORD` is not set, the middleware returns `NextResponse.next()` -- all admin pages and API routes are **publicly accessible without authentication**. This is documented behavior for dev, but there is no visual indicator on the admin UI that auth is disabled. An operator might deploy without setting the password and not realize the admin panel is open.
- Login page, login API, and logout API are correctly excluded from auth checks.

### API Routes

- All admin API routes use `revalidate = 300` (5 minutes) for ISR caching. Appropriate for operational data that doesn't change rapidly.

---

## Cross-Cutting Concerns

### Responsive Behavior

- `AdminShell` implements a proper responsive pattern: desktop sidebar (hidden on mobile via `lg:hidden`/`lg:block`), mobile hamburger menu with slide-in sidebar and backdrop overlay.
- Mobile header is sticky with `z-30`, sidebar overlay is `z-40`, sidebar is `z-50`. Z-index layering is correct.
- Main content area uses `max-w-7xl` with responsive padding (`px-4 sm:px-6 lg:px-8`). Good.
- **Enhancement E5:** The mobile sidebar close button uses an X icon but does not trap focus. For accessibility, the mobile overlay should trap focus within the sidebar when open.

### Navigation

- `AdminNav` uses `usePathname()` for active state detection. The overview route (`/admin`) uses exact match while sub-routes use `startsWith`. This is correct and avoids false active states.
- Five nav items: Overview, Content, Pipeline, Profiling, Health. All with Lucide icons.
- "Back to docs" and "Sign out" links in the sidebar footer. Good escape hatches.

### Animation

- `nba-reveal` with staggered `nba-delay-1/2/3` classes (80ms/160ms/240ms) provides a pleasant fade-up entrance. Each page section animates in sequence.
- The fade-up animation uses `opacity: 0` initial state. **DEFECT D17:** If CSS fails to load or animations are disabled (prefers-reduced-motion), all admin content will be invisible (`opacity: 0`). There is no `@media (prefers-reduced-motion: reduce)` override to set `opacity: 1` and disable the animation.

### Typography

- `nba-kicker` (0.65rem, 600 weight, uppercase tracking) is used consistently for labels above KPI values and section kickers. Creates a cohesive metric-card feel.
- `nba-scoreboard-value` (monospace, tabular-nums) is used for KPI values. Good for number alignment.

---

## Defects

| ID | Severity | Location | Description |
|----|----------|----------|-------------|
| D1 | Medium | `admin/page.tsx:15-24` | Server component fetches its own API routes over HTTP instead of calling data functions directly. Adds latency and failure mode. |
| D2 | Low | `content/content-table.tsx:33` | `max-w-xs truncate` on `<td>` inside a table does not truncate without `table-layout: fixed`. Long descriptions overflow. |
| D3 | Medium | `content/content-table.tsx` | No search/filter input on content table. Operator must scan/sort manually. |
| D4 | High | `content/page.tsx:16-20` | Content freshness data is entirely synthetic (based on slug length), not actual file age. Heatmap is misleading. |
| D5 | Low | `pipeline/pipeline-charts.tsx:37-38` | Endpoint name truncation cuts mid-word with no ellipsis. |
| D6 | Low | `pipeline/pipeline-charts.tsx:41-47` | Donut chart renders empty when all status counts are zero but other telemetry arrays have data. |
| D7 | Low | `chart-area.tsx:32` | SVG gradient ID collision if multiple area charts share the same `yKey`. |
| D8 | Medium | `pipeline/pipeline-tabs.tsx` | `PipelineTabs` component is implemented but never used. Tab switching is dead code. |
| D9 | Low | `pipeline/pipeline-history.tsx:20-24` | `trends` prop is accepted but never rendered. Dead prop. |
| D10 | Low | `profiling/page.tsx:95-97` | Unknown data layers sort to top of list due to `indexOf` returning -1. |
| D11 | Medium | `profiling/page.tsx:122-157` | Profiling tables have no sorting capability. Cannot find outlier tables by row/column count. |
| D12 | Low | `profiling/page.tsx` | No pagination on profiling tables. Large layers render very tall cards. |
| D13 | Medium | `health/page.tsx:63-72` | Dependency versions are hardcoded and will drift from actual installed versions. |
| D14 | Medium | `health/page.tsx:48-52` | Build and Search subsystem statuses are hardcoded as "healthy" with no actual checks. |
| D15 | Medium | `health/page.tsx:38-42` | Search health is hardcoded. No verification of Orama index. |
| D16 | Low | `middleware.ts:49` | When ADMIN_PASSWORD is unset, admin is fully public with no visual warning. |
| D17 | High | `global.css:544-546` | `nba-reveal` sets `opacity: 0` with no `prefers-reduced-motion` fallback. Content is invisible if animations are blocked. |

---

## Enhancement Ideas

| ID | Priority | Description |
|----|----------|-------------|
| E1 | Low | Only animate StatusDot ping on non-healthy statuses to reduce visual noise. |
| E2 | Low | Humanize latency display: show "1.2s" instead of "1200ms" for large values. |
| E3 | Low | Add "ms" unit label to BarList values in the Slowest Endpoints card. |
| E4 | Medium | Add a refresh/recheck button on the health page. |
| E5 | Medium | Implement focus trapping in the mobile sidebar overlay for accessibility. |
| E6 | Medium | Wire `PipelineTabs` into the pipeline page to enable the history view. |
| E7 | High | Implement actual content freshness from git timestamps or file mtime. |
| E8 | Medium | Add a global filter/search input to the content table. |
| E9 | Medium | Read dependency versions from `package.json` at build time instead of hardcoding. |
| E10 | Low | Add a visual banner when ADMIN_PASSWORD is not configured to warn about open access. |
| E11 | Medium | Add sorting to profiling tables (reuse DataTable component). |
| E12 | Low | Add `prefers-reduced-motion` media query override for `nba-reveal` animation. |
| E13 | Low | Use a unique prefix (e.g., component instance ID) for SVG gradient IDs to avoid collisions. |
| E14 | Medium | Use the `trend` prop on overview KPI cards to show week-over-week changes when analytics data is available. |

---

## Notes

1. **Overall architecture quality is high.** The admin panel follows a clean pattern: server components for data fetching, client components for interactivity, a shared component library (`components/admin/`), and typed data modules (`lib/admin/`). The separation of concerns is well-executed.

2. **The pipeline data path is well-designed** but currently empty in local dev. The `getPipelineSummary()` function tries 3 file paths and falls back to `EMPTY_SUMMARY` with all zeroes. The empty-state messaging throughout the pipeline page is consistently helpful, guiding the operator to the CLI command to generate data.

3. **The `DataTable` generic component is solid.** Sorting, pagination, hover states, and responsive overflow scrolling all work correctly. The TanStack React Table integration is clean with proper type handling.

4. **Chart components are minimal but effective.** All three chart types (area, bar, donut) use Recharts with consistent tooltip styling, appropriate colors from CSS variables, and responsive containers. The donut lacks a legend (relies only on tooltip), which could be improved for static screenshots or quick glances.

5. **The admin shell responsive pattern is correct** with desktop sidebar, mobile hamburger, overlay backdrop, and proper z-index stacking. The logout flow properly clears the session cookie via the API.

6. **Live page capture (while server was running)** confirmed:
   - Overview page renders with 49 total pages, 0 missing descriptions, analytics placeholder, health subsystems (Search healthy, Pipeline unknown, Content healthy), and empty pipeline tracker.
   - Content page renders the full sortable table with all 49 docs pages, section badges, and description columns.
   - The server crashed after content page capture (connection refused on subsequent requests), suggesting possible instability under rapid sequential requests or a hot-reload issue during dev.

7. **The `PipelineTabs` dead code (D8) is the most impactful unused feature.** The History tab with freshness heatmap and health scores would be valuable for operators but is currently invisible because the pipeline page renders `PipelineCharts` directly.
