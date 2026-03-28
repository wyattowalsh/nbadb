# Audit G: Interactive Widget Lab

**Auditor:** Code-based static analysis + URL verification (Chrome DevTools not available during session)
**Date:** 2026-03-28
**Scope:** All interactive MDX components in the nbadb docs site

---

## SQL Playground

### Load Behavior

- **Lazy initialization.** DuckDB-WASM only loads when the user clicks "Run" or presses Cmd+Enter. Before that, the UI shows "Click Run to initialize" in the status bar and a gentle empty-state message: "Pick an example or write your own SQL, then press Run to initialize DuckDB-WASM in this tab." This is a good UX choice -- no wasted bandwidth on page load.
- **Singleton pattern.** `lib/duckdb.ts` uses a module-level `dbInstance` / `initPromise` pair so the WASM engine loads once and is reused across queries within a tab. Multiple `SqlPlayground` instances on the same page share the engine.
- **CDN dependency.** WASM bundles are fetched from jsDelivr via `duckdb.getJsDelivrBundles()`. If jsDelivr is unreachable (corporate proxy, CDN outage), initialization fails with no retry and no fallback.
- **Dev version in use.** `@duckdb/duckdb-wasm` is pinned to `1.33.1-dev20.0` -- a development pre-release. This may carry bugs not present in stable releases and its jsDelivr bundle could be removed without notice.
- **Loading spinner.** The Run button shows a Loader2 spinner and "Running..." text while the query executes. The button is disabled during execution to prevent double-submits.
- **Parquet progress.** When loading multiple Parquet tables, a progress indicator displays "Loading {tableName} ({n}/{total})...". This is clear and helpful.

### Query Execution

- **Default query works standalone.** The first playground uses inline `VALUES` data -- no external dependencies. `SELECT 42 AS answer, 'Hello from DuckDB-WASM!' AS message;` will succeed immediately after WASM loads.
- **CRITICAL: Second playground Parquet URLs return 404.** The second `SqlPlayground` on the page references five Parquet files from `https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/`. The GitHub release tag `docs-sample-data` does not exist and the repository has zero releases. All five URLs (`dim_player_sample.parquet`, `dim_team_sample.parquet`, `agg_player_season_sample.parquet`, `fact_shot_chart_sample.parquet`, `fact_standings_sample.parquet`) return HTTP 404. Clicking "Run" on the second playground will fail with a DuckDB error about being unable to read the Parquet file.
- **Result capping.** Results are capped at 1,000 rows with a clear footer message: "Showing first 1,000 rows". Good defensive measure against unbounded result sets.
- **Chart inference.** The `ResultToolbar` component runs `inferChart()` on every result set and conditionally shows a Chart toggle button. The inference logic classifies columns as temporal/categorical/quantitative and maps to bar/line/scatter/grouped-bar/multi-line. The chart module (`PlotFromResult`) is lazy-loaded only when the Chart tab is clicked.
- **Keyboard shortcut.** Cmd+Enter / Ctrl+Enter runs the query. This is standard and well-implemented. The hint text shows the shortcut in the toolbar.
- **Example buttons.** One-click example queries load into the textarea and highlight the active example pill. Clicking an example clears previous results and errors. Good flow.

### Error Handling

- **DuckDB errors surfaced clearly.** Errors are caught in the `runQuery` callback and displayed in a red-tinted banner below the editor (`bg-destructive/5`, `text-destructive`). The raw error message from DuckDB is shown, which is helpful for SQL debugging.
- **Init failure.** If DuckDB-WASM fails to initialize (network error, WASM load failure), the error is shown in the same error banner. No retry mechanism is offered.
- **No input sanitization.** The playground is intended as a sandbox -- users can run arbitrary SQL. The DuckDB-WASM engine runs entirely in the browser, so this is safe by design (no server-side injection risk). The `registerParquet` function validates table names with `/^[a-z_][a-z0-9_]*$/i` and escapes single quotes in URLs -- reasonable defense-in-depth.

### Responsiveness

- **Textarea resizable.** The `resize-y` class allows vertical resizing. The textarea starts at 10 rows.
- **Horizontal scroll on results.** The result table uses `overflow-x-auto` to handle wide result sets.
- **Mobile considerations.** The status bar hides on small screens (`max-sm:hidden`). The "Tables:" info also hides on mobile. Example buttons wrap via `flex-wrap`. The layout is functional on mobile but the textarea + result table combination may be cramped on very small screens.
- **No code editor features.** The textarea is a plain HTML `<textarea>` -- no syntax highlighting, no autocomplete, no line numbers. This is a deliberate simplicity choice but limits the experience for complex queries.

---

## Other Interactive Components

### Observable Plot Charts

- **Well-architected lazy loading.** All chart components (`ShotChart`, `GameFlow`, `PlayerCompare`, `SeasonTrend`, `DistributionPlot`, `HeatmapGrid`) are exported through `dynamic-charts.tsx` using `next/dynamic` with `{ ssr: false }`. This prevents server-side rendering errors from Observable Plot's DOM dependency.
- **Theme-aware.** All plots use `background: "transparent"` and `color: "currentColor"` so they inherit the site's light/dark theme automatically. The `ShotChart` uses hardcoded NBA colors (`#00A651` green for makes, `#C8102E` red for misses) which is appropriate for the domain.
- **CourtSvg integration.** The `ShotChart` component overlays dots on a pure-SVG half-court diagram (`court-svg.tsx`) using absolute positioning. The SVG viewBox matches nba_api coordinates. The court stroke color uses `color-mix(in oklch, currentColor 20%, transparent)` for subtle theme adaptation.
- **Tooltips enabled.** All Plot marks use `tip: true` for hover tooltips.
- **Cleanup on unmount.** The `useEffect` return in `ObservablePlot` calls `plot.remove()` to clean up the DOM. Correct pattern.
- **NOT CURRENTLY USED.** None of these chart components (`ShotChart`, `GameFlow`, `PlayerCompare`, `SeasonTrend`, `DistributionPlot`, `HeatmapGrid`, `ObservablePlot`) are invoked in any MDX content page. They are registered in `mdx.tsx` but zero MDX files use them. They exist as infrastructure for future content.

### Tabs / Dynamic Content

- **Fumadocs Tabs.** Used on the Role-Based Onboarding Hub page (`role-based-onboarding-hub.mdx`). Imports `Tab` and `Tabs` from `fumadocs-ui/components/tabs`, which uses Radix `@radix-ui/react-tabs` under the hood. This is a well-tested, accessible tabs implementation.
- **Tab content is rich.** Each tab contains `CommandBlock`, `ScoutCard`, `InsightCard`, and grid layouts. These render correctly within Fumadocs tabs.
- **State preservation.** Radix Tabs renders all tab panels into the DOM and toggles visibility, so form state within tabs is preserved when switching. This is the correct behavior.
- **Single usage.** Tabs are only used on one page in the entire docs site.

### Schema Explorer

- **Component complete and well-built.** Two-column layout (table list + detail panel), search with debounce (200ms), family filter pills (dim/fact/bridge/agg/analytics), column listing with key badges (PK/FK), and navigable foreign-key relationships.
- **NOT CURRENTLY USED.** The `<SchemaExplorer>` JSX tag is not used in any MDX page. The component is registered in the MDX component map but there is no page that passes it a `data` prop with schema JSON.

### Lineage Explorer

- **Component complete and well-built.** Three-panel layout (upstream / selected / downstream), BFS graph traversal with configurable depth (1 hop / 2 hops / all), search with debounce (150ms), layer filter pills matching the lineage color scheme, column listing with expand/collapse.
- **NOT CURRENTLY USED.** The `<LineageExplorer>` JSX tag is not used in any MDX page. The component is registered in the MDX component map but there is no page that passes it a `data` prop with lineage JSON. The `lineage.json` file exists at `content/docs/lineage/lineage.json` but is not wired to the component.

### Mermaid Diagrams

- **Pervasive usage.** Mermaid diagrams appear on 12+ pages across architecture, lineage, schema, data-dictionary, pipeline-flow, and guides. Both fenced code blocks (`\`\`\`mermaid`) and the `<Mermaid>` JSX component are used. The `remarkMdxMermaid` remark plugin (from `fumadocs-core/mdx-plugins`) converts fenced blocks to `<Mermaid chart="..."/>` during the MDX compile step, so both approaches use the same runtime component.
- **Zoom/pan support.** The Mermaid component includes a full zoom-pan system (`useZoomPan` hook) with scroll-to-zoom, drag-to-pan, keyboard shortcuts (+/- zoom, arrows pan, 0 reset, Home fit), and a toolbar with zoom percentage display.
- **Theme-aware.** Reads CSS custom properties from `document.documentElement` at render time and passes them as mermaid theme variables. Re-renders when `resolvedTheme` changes (via `next-themes`).
- **Caching.** Uses a module-level `Map` cache keyed by `chart-resolvedTheme`. This prevents re-rendering the same diagram when the component re-mounts.
- **SSR fallback.** Shows a source-code preview of the mermaid definition with "Preparing board" / "Rendering board" status messages during hydration and async rendering (uses `<Suspense>`).
- **Performance concern: 1,056-line lineage-auto diagram.** The `lineage-auto.mdx` file contains a single mermaid flowchart with ~1,056 lines of node and edge definitions (hundreds of staging tables, endpoints, dimensions, facts, bridges, aggregations, and analytics). Mermaid's rendering performance degrades significantly at this scale. The browser may freeze for several seconds during the initial render. There is no virtualization or progressive rendering.
- **`securityLevel: "loose"`.** The mermaid initialization uses `securityLevel: "loose"`, which allows HTML in mermaid labels and click events. Since the mermaid definitions are author-controlled (from MDX source, not user input), this is acceptable but worth noting.

---

## Defects

| # | Severity | Component | Description |
|---|----------|-----------|-------------|
| D1 | **P0 -- Blocker** | SqlPlayground (Parquet) | The second SQL Playground on `/docs/playground` references five Parquet files at `https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/*.parquet`. The GitHub release tag `docs-sample-data` does not exist and the repository has zero releases. All five URLs return HTTP 404. The "Query real NBA data" section is completely non-functional. |
| D2 | **P2 -- Minor** | SqlPlayground | DuckDB-WASM is pinned to a dev pre-release (`1.33.1-dev20.0`). Dev versions may be removed from CDN or contain regressions. Should pin to a stable release. |
| D3 | **P2 -- Minor** | SqlPlayground | No retry or offline fallback when DuckDB-WASM WASM bundles fail to load from jsDelivr CDN. Users behind restrictive proxies or during CDN outages see a single error with no recovery path. |
| D4 | **P3 -- Low** | Mermaid | The lineage-auto diagram (~1,056 lines, hundreds of nodes+edges) may cause multi-second browser freezes during rendering. No loading indicator is shown during the mermaid `render()` call itself (only during initial module load). |

## Enhancement Ideas

| # | Priority | Component | Description |
|---|----------|-----------|-------------|
| E1 | High | SqlPlayground | Create the `docs-sample-data` GitHub release and upload the five sample Parquet files referenced in `parquet-catalog.ts` and `playground.mdx`. Alternatively, host them in a more reliable location (R2, S3, or checked into the repo as LFS objects). |
| E2 | High | LineageExplorer | Wire the `LineageExplorer` component to the existing `lineage.json` data on the lineage index or lineage-auto page. The component is fully built and would provide a significantly better interactive experience than the 1,056-line static Mermaid diagram. |
| E3 | High | SchemaExplorer | Wire the `SchemaExplorer` component to schema data on the schema index page. The component is fully built and would replace the need to navigate between multiple reference pages. |
| E4 | Medium | SqlPlayground | Add syntax highlighting to the SQL editor. Options: swap the `<textarea>` for CodeMirror 6 (already used by many DuckDB playgrounds) or use a lightweight approach like `react-simple-code-editor` with a Prism.js SQL grammar. |
| E5 | Medium | SqlPlayground | Add a "Copy results as CSV" or "Copy as TSV" button to the result table toolbar. |
| E6 | Medium | Mermaid | For the lineage-auto diagram, consider splitting it into multiple smaller diagrams (by layer or family) or using the already-built `LineageExplorer` component instead. |
| E7 | Low | SqlPlayground | Show estimated WASM download size (~5 MB for DuckDB-WASM + Parquet data) before the user clicks Run, so they know what to expect on slow connections. |
| E8 | Low | SqlPlayground | Add a query history feature (localStorage-backed) so users can recall previous queries within a session. |
| E9 | Low | Observable Plot | Create at least one MDX page that uses the chart components (ShotChart, GameFlow, etc.) to validate them with real content. Currently all chart components are untested dead code from the docs perspective. |
| E10 | Low | DuckDB lib | Pin `@duckdb/duckdb-wasm` to a stable release (e.g., `1.29.0` or latest stable) instead of a `-dev` pre-release. |

## Notes

### Component Inventory

| Component | File | Used in MDX? | Status |
|-----------|------|-------------|--------|
| SqlPlayground | `components/mdx/sql-playground.tsx` | Yes (`playground.mdx`) | Functional (first instance); broken (second instance -- 404 Parquet) |
| Mermaid | `components/mdx/mermaid.tsx` | Yes (12+ pages) | Functional; performance concern on large diagrams |
| ObservablePlot | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| ShotChart | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| GameFlow | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| PlayerCompare | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| SeasonTrend | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| DistributionPlot | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| HeatmapGrid | `components/mdx/observable-plot.tsx` | No | Dead code -- registered but unused |
| PlotFromResult | `components/mdx/plot-from-result.tsx` | Indirectly (via SqlPlayground Chart toggle) | Functional but only reachable if chart inference succeeds |
| CourtSvg | `components/mdx/court-svg.tsx` | No (only used by ShotChart) | Dead code -- registered but unused |
| SchemaExplorer | `components/mdx/schema-explorer.tsx` | No | Dead code -- registered but unused |
| LineageExplorer | `components/mdx/lineage-explorer.tsx` | No | Dead code -- registered but unused |
| Fumadocs Tabs | `fumadocs-ui/components/tabs` | Yes (1 page) | Functional |

### Architecture Quality

The interactive component architecture is well-designed:
- Clean separation between lazy-loaded wrappers (`dynamic-charts.tsx`) and implementations
- Proper SSR guards (`"use client"`, `next/dynamic` with `ssr: false`, `useState(false)` mount guards)
- Theme-aware rendering throughout
- Accessible markup (ARIA labels on Mermaid viewport, keyboard handlers, focus-visible styles)
- Defensive coding (table name validation, URL escaping, result capping)

The main gap is that a significant amount of high-quality interactive component code (LineageExplorer, SchemaExplorer, all Observable Plot charts) has been built but never wired into any content page. Activating these would substantially improve the docs site's interactive capabilities.

### Security Notes

- DuckDB-WASM runs entirely in the browser tab -- no server-side SQL execution risk
- `registerParquet` validates table names with a strict alphanumeric regex
- Mermaid uses `securityLevel: "loose"` but all diagram definitions are author-controlled (compiled from MDX at build time, not from user input)
- No user-supplied data flows into SQL or Mermaid definitions beyond the playground textarea, which only executes in the browser sandbox
