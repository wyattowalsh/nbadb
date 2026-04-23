# Docs Admin Page Inventory

## Purpose
- Grouped internal extract manifest for the password-protected docs admin surface: the route-group shell, login entry, overview page, content page, pipeline page, profiling page, and health page, plus the reusable child components and auth or data boundaries that most directly define each screen.

## High-value paths

### Route-group shell and auth boundary
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/layout.tsx` | Route-group layout for every admin page; applies no-index metadata, wraps children in `AdminShell`, and shows the operator warning when `ADMIN_PASSWORD` is missing. |
| `docs/components/admin/admin-shell.tsx` | Core control-center frame: desktop sidebar, mobile drawer, focus trap, escape handling, back-to-docs affordance, sign-out action, and the main content container used by every admin page. |
| `docs/components/admin/admin-nav.tsx` | Canonical navigation map for the five page surfaces: overview, content, pipeline, profiling, and health. |
| `docs/proxy.ts` | Request gate for `/admin/:path*` and `/api/admin/:path*`; allows only login and logout public paths, redirects page requests to `/admin/login`, and returns `401` or `503` for API callers. |
| `docs/lib/admin/session.ts` | Shared HMAC session-cookie contract used by the proxy and the login or logout handlers. |

### Login page and session entry
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/login/page.tsx` | Client login screen; posts the password to `/api/admin/login`, shows inline loading and error states, and navigates to `/admin` on success. |
| `docs/app/api/admin/login/route.ts` | Login API boundary; enforces `ADMIN_PASSWORD`, applies per-process rate limiting, uses timing-safe password comparison, and issues the signed admin session cookie. |
| `docs/app/api/admin/logout/route.ts` | Logout API boundary; clears the admin session cookie so `AdminShell` can sign operators out cleanly. |
| `docs/components/ui/button.tsx` | Shared submit affordance used by the login form and other admin actions. |

### Overview page and dashboard primitives
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/page.tsx` | Overview route; composes content audit, pipeline summary, and optional Umami stats into the control-center landing page. |
| `docs/app/(admin)/admin/overview-sparklines.tsx` | Client child for overview analytics; fetches 7 day and 30 day pageview series from `/api/admin/umami` and renders loading and analytics-disabled states. |
| `docs/components/admin/kpi-card.tsx` | Primary compact metric card used across overview, content, pipeline, profiling, and health. |
| `docs/components/admin/tracker-bar.tsx` | Overview child for pipeline-run state strips. |
| `docs/components/admin/bar-list.tsx` | Overview child for section-count ranking and other small bar-list breakdowns. |
| `docs/components/admin/status-dot.tsx` | Overview child for the lightweight subsystem-health summary. |
| `docs/components/admin/sparkline-card.tsx` | Inline trend card used by `OverviewSparklines`. |
| `docs/lib/admin/content-audit.ts` | Source-backed inventory loader that powers overview content totals, missing descriptions, shallow TOC counts, and section breakdowns. |
| `docs/lib/admin/pipeline.ts` | JSON-backed pipeline summary loader that powers overview pipeline health and tracker strips. |
| `docs/lib/admin/umami.ts` | Optional analytics adapter used by the overview page when Umami env vars are present. |

### Content page and content-audit children
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/content/page.tsx` | Content analytics route; turns the source audit into KPI cards, the all-pages table, section breakdowns, freshness tiles, and explicit missing-description findings. |
| `docs/app/(admin)/admin/content/filterable-content-table.tsx` | Client wrapper that adds free-text and section filters before delegating to `ContentTable`. |
| `docs/app/(admin)/admin/content/content-table.tsx` | Content-page table definition; configures columns for title, section, description, and TOC depth. |
| `docs/components/admin/data-table.tsx` | TanStack table shell used by both content and profiling page tables for sorting and pagination. |
| `docs/components/admin/content-freshness.tsx` | Content-page freshness visualization that bins docs pages by age using compact colored tiles. |
| `docs/components/admin/bar-list.tsx` | Content-page child for the pages-by-section ranking. |
| `docs/lib/admin/content-audit.ts` | Canonical source index for page metadata, file mtimes, section counts, missing descriptions, and shallow TOC detection. |

### Pipeline page and telemetry tabs
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/pipeline/page.tsx` | Pipeline route; builds the hero summary, KPI grid, current extraction state, failure hotspots, telemetry window cards, tabbed charts or history, and recent errors. |
| `docs/app/(admin)/admin/pipeline/pipeline-tabs.tsx` | Tab switcher that separates the pipeline page into current-state charts and history views. |
| `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` | Current-state chart composition for extraction volume, p95 endpoint latency, and status breakdown. |
| `docs/app/(admin)/admin/pipeline/pipeline-history.tsx` | History tab child that turns endpoint freshness and health scores into KPI cards, a freshness heatmap, and ranked health-score rows. |
| `docs/components/admin/chart-area.tsx` | Shared Recharts area wrapper used for pipeline extraction-volume series. |
| `docs/components/admin/chart-bar.tsx` | Shared Recharts bar wrapper used for endpoint-latency comparisons. |
| `docs/components/admin/chart-donut.tsx` | Shared Recharts donut wrapper used for status distribution. |
| `docs/components/admin/freshness-heatmap.tsx` | Pipeline-history child for endpoint freshness grouped by layer. |
| `docs/components/admin/tracker-bar.tsx` | Pipeline-page child for recent extraction status blocks. |
| `docs/components/admin/bar-list.tsx` | Pipeline-page child for failure hotspots and slow-endpoint lists. |
| `docs/lib/admin/pipeline.ts` | Pipeline telemetry loader and status mapping contract consumed throughout the pipeline route. |
| `docs/app/api/admin/pipeline-status/route.ts` | Machine-readable summary export for pipeline telemetry plus computed overall status. |

### Profiling page and layered table views
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/profiling/page.tsx` | Profiling route; searches the candidate JSON locations for table-profile data, renders the empty-state regenerate hint, groups profiles by layer, and exposes summary KPI cards. |
| `docs/app/(admin)/admin/profiling/profiling-layer-table.tsx` | Per-layer table child that defines the profiling columns and the compact column-profile pill list. |
| `docs/components/admin/data-table.tsx` | Generic tabular shell reused for profiling layer tables. |
| `docs/lib/admin/files.ts` | JSON fallback reader used to search the profiling artifact locations and distinguish missing files from malformed JSON. |
| `docs/lib/admin/types.ts` | Shared `TableProfile` and `ColumnProfile` contract consumed by the profiling route and its table child. |

### Health page and subsystem status lane
| Path | Inventory role |
| --- | --- |
| `docs/app/(admin)/admin/health/page.tsx` | Human-facing health route; combines content inventory, pipeline summary, package-version inspection, KPI cards, and subsystem status rows. |
| `docs/app/api/admin/health/route.ts` | Machine-readable health endpoint that returns build, search, pipeline, and content subsystem states plus overall status. |
| `docs/components/admin/status-dot.tsx` | Shared subsystem-row primitive used most visibly on the health page. |
| `docs/components/admin/kpi-card.tsx` | Health-page child for page counts, pipeline-table totals, and staging coverage. |
| `docs/lib/admin/content-audit.ts` | Health-page content inventory source. |
| `docs/lib/admin/pipeline.ts` | Health-page pipeline inventory source and pipeline-to-health mapping boundary. |
| `docs/lib/admin/types.ts` | Shared `HealthCheck` and `SubsystemStatus` contract used by the API and page. |

## Notes
- The admin page inventory is split between route-group policy and page-specific UI. `layout.tsx`, `proxy.ts`, and `session.ts` define whether operators can reach the surface at all; the individual pages mostly assume the shell and auth gate already succeeded.
- The overview, content, pipeline, profiling, and health pages are server-rendered entry points that hand off the most interactive work to small client children such as `OverviewSparklines`, `FilterableContentTable`, `PipelineTabs`, `PipelineHistory`, and `ProfilingLayerTable`.
- Reuse is deliberate. `KpiCard`, `StatusDot`, `TrackerBar`, `BarList`, `DataTable`, and the chart wrappers form the stable component vocabulary for the admin control plane, so page differences mostly come from their loaders and page-local composition.
- Content is source-backed, while pipeline and profiling are JSON-backed. `content-audit.ts` reads the live Fumadocs source graph and file mtimes; `pipeline.ts` and `readFirstJson()` read generated artifacts and shape empty states instead of querying live pipeline state.
- The login flow is intentionally narrow: the page posts only to `/api/admin/login`, the proxy treats `/admin/login`, `/api/admin/login`, and `/api/admin/logout` as the only public admin paths, and `AdminShell` signs out through the logout handler rather than mutating cookies directly.
- Health has two surfaces with different emphasis. The API route returns a cacheable machine-readable status snapshot, while the page adds package versions and labels build health as runtime-unverified instead of probing build integrity directly.

## Planned wiki coverage
- `wiki/topics/docs-admin-surface.md`
- `wiki/topics/docs-telemetry-health.md`
- `wiki/topics/docs-component-registry.md`
- future `wiki/topics/docs-admin-auth-flow.md`
- future `wiki/topics/docs-pipeline-dashboard.md`
- future `wiki/topics/docs-content-audit.md`

## Provenance
- `docs/app/(admin)/admin/layout.tsx`
- `docs/components/admin/admin-shell.tsx`
- `docs/components/admin/admin-nav.tsx`
- `docs/proxy.ts`
- `docs/lib/admin/session.ts`
- `docs/app/(admin)/admin/login/page.tsx`
- `docs/app/api/admin/login/route.ts`
- `docs/app/api/admin/logout/route.ts`
- `docs/app/(admin)/admin/page.tsx`
- `docs/app/(admin)/admin/overview-sparklines.tsx`
- `docs/app/(admin)/admin/content/page.tsx`
- `docs/app/(admin)/admin/content/filterable-content-table.tsx`
- `docs/app/(admin)/admin/content/content-table.tsx`
- `docs/app/(admin)/admin/pipeline/page.tsx`
- `docs/app/(admin)/admin/pipeline/pipeline-tabs.tsx`
- `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx`
- `docs/app/(admin)/admin/pipeline/pipeline-history.tsx`
- `docs/app/(admin)/admin/profiling/page.tsx`
- `docs/app/(admin)/admin/profiling/profiling-layer-table.tsx`
- `docs/app/(admin)/admin/health/page.tsx`
- `docs/app/api/admin/health/route.ts`
- `docs/app/api/admin/pipeline-status/route.ts`
- `docs/lib/admin/content-audit.ts`
- `docs/lib/admin/pipeline.ts`
- `docs/lib/admin/files.ts`
- `docs/lib/admin/types.ts`
- `docs/lib/admin/umami.ts`
- `docs/components/admin/kpi-card.tsx`
- `docs/components/admin/tracker-bar.tsx`
- `docs/components/admin/status-dot.tsx`
- `docs/components/admin/bar-list.tsx`
- `docs/components/admin/chart-area.tsx`
- `docs/components/admin/chart-bar.tsx`
- `docs/components/admin/chart-donut.tsx`
- `docs/components/admin/sparkline-card.tsx`
- `docs/components/admin/content-freshness.tsx`
- `docs/components/admin/freshness-heatmap.tsx`
- `docs/components/admin/data-table.tsx`
- `docs/components/ui/button.tsx`
