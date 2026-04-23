---
title: Visualization Surface
tags:
  - kb
  - topics
  - visualization
  - docs
  - chat
aliases:
  - Visualization Surfaces
  - Docs and Chat Visualization Surface
kind: concept
status: active
updated: 2026-04-22
source_count: 14
---

# Visualization Surface

This note maps the repo's visualization lanes across `docs/` and `chat/` so you can choose the right surface instead of mixing docs-site widgets, admin charts, and chat artifacts.

## Surface map
| Surface | Primary home | Best use | Do not use it for |
| --- | --- | --- | --- |
| Observable Plot | docs MDX and docs-side result rendering | interactive explanatory charts inside docs pages | chat exports or admin dashboards |
| Recharts | docs admin area | operational dashboards, sparklines, KPI-adjacent monitoring | public docs examples or chat analysis |
| Plotly | chat sandbox + Chainlit renderer | interactive analysis charts, hoverable comparisons, embeddable figures | docs MDX showcase components |
| matplotlib | chat sandbox helpers | specialized court diagrams, shot maps, radar charts, static PNG output | docs admin charts or rich interactive UI |
| Shot charts | docs and chat, but with different implementations | docs demos in MDX, chat analysis in Python | generic ranking/comparison charts |
| Social cards | docs OG image routes and chat export helpers | shareable branded images | exploratory analysis inside the app |
| Embeds | chat export helpers | self-contained HTML you can drop into a site or blog | native docs-authoring components |

## Docs lane

### Observable Plot is the docs-native chart system
- `docs/AGENTS.md` names Observable Plot as the main docs visualization system.
- `docs/components/mdx/observable-plot.tsx` owns the reusable docs components: `ObservablePlot`, `ShotChart`, `GameFlow`, `PlayerCompare`, `SeasonTrend`, `DistributionPlot`, and `HeatmapGrid`.
- `docs/components/mdx/dynamic-charts.tsx` makes those widgets client-only via dynamic import and wraps them in a widget error boundary.
- `docs/components/mdx.tsx` registers them for MDX so authored docs pages can use them directly.

Use Observable Plot when the chart is part of the documentation itself: examples, walkthroughs, small analytical demos, and result viewers embedded in MDX.

### Docs shot charts are explanatory widgets, not the full analysis runtime
- The docs `ShotChart` overlays Plot dots on `CourtSvg`, using NBA shot coordinates and make/miss coloring.
- `docs/content/docs/start/shot-chart-analysis.mdx` uses that component as a live preview for the guide.
- `docs/content/docs/start/analytics-quickstart.mdx` frames shot-location pulls as the upstream query pattern that later feeds plotting.

Use the docs shot-chart component when teaching the coordinate frame or illustrating a guide. It is not the main artifact-export path.

### Recharts belongs to docs admin and monitoring
- `docs/AGENTS.md` assigns Recharts to the admin dashboard.
- `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` composes `ChartArea`, `ChartBar`, and `ChartDonut` for extraction volume, latency, and status breakdowns.
- `docs/components/admin/chart-area.tsx` and the sibling admin wrappers are thin Recharts shells for responsive operational charts.
- `docs/app/(admin)/admin/overview-sparklines.tsx` uses admin sparkline cards for traffic-style telemetry.

Use Recharts for admin and observability views where the chart is part of the docs application's product UI rather than authored documentation content.

### Docs social cards are OG-image routes
- `docs/app/opengraph-image.tsx` generates the site-wide social card.
- `docs/app/docs-og/{catch-all}/route.tsx` generates per-page OG cards based on section metadata and page frontmatter.

Use these when the docs site needs share previews. They are not user-triggered analysis exports.

## Chat lane

### Plotly is the main interactive analysis surface
- `src/nbadb/chat/prompts.py` explicitly says Plotly is preferred for interactive charts.
- The prompt's chart-selection table routes rankings, trends, scatter plots, distributions, and part-of-whole charts to Plotly.
- `src/nbadb/chat/app/preamble.py` pre-imports `plotly.express` and `plotly.graph_objects`, and exposes `chart()` plus `annotated_chart()`.
- `chat/chainlit_app.py` renders Plotly JSON inline with `cl.Plotly`.

Use Plotly when the user is exploring data live in chat and benefits from hover, zoom, legends, reference lines, and easy HTML export.

### matplotlib is the specialized static-analysis lane
- The sandbox preamble forces matplotlib onto `Agg` and patches `plt.show()` into base64 PNG output.
- `chat/chainlit_app.py` renders those outputs as inline images.
- The prompt and skill files keep matplotlib for specialized visuals, especially court diagrams and shot charts.

Use matplotlib when the figure geometry is custom or court-specific, or when the helper script already returns a static figure.

### Chat shot charts are Python helpers, not MDX widgets
- `chat/skills/nba-data-analytics/scripts/court.py` owns `draw_court`, `shot_chart`, `shot_heatmap`, `zone_chart`, and `compare_shots`.
- `src/nbadb/chat/prompts.py` routes shot-location questions to `court.shot_chart(df)` and `court.shot_heatmap(df)`.
- `chat/skills/nba-data-analytics/SKILL.md` ties those helpers to `fact_shot_chart` and its location and zone columns.

Use the chat shot-chart helpers when the user wants actual analysis artifacts from warehouse data, not a docs example.

### Other chat helper scripts split by output type
- `compare.py` includes a matplotlib radar chart and tabular comparison helpers.
- `lineups.py` returns a Plotly bar chart for lineup comparisons.
- `analysis-and-visualization/SKILL.md` keeps the decision rule simple: SQL for retrieval, Python for post-processing, statistics, charting, and exports.

## Share surfaces

### Embeds belong to chat exports
- `src/nbadb/chat/app/preamble.py` provides `to_embed(fig, title)`, which serializes a Plotly figure into a self-contained HTML snippet wrapped in an `nbadb-embed` container.
- `src/nbadb/chat/prompts.py` positions embeds as the right answer when the user asks to embed a chart in a blog or site.

Use embeds when the output needs to leave chat and run elsewhere. Docs MDX components are for repo-authored pages, not portable user exports.

### Social cards split into two different products
- In docs, OG image routes produce page and site share cards automatically.
- In chat, `to_social(df_or_fig, headline, subtitle)` renders a 1200x630 branded PNG card for user-directed sharing.

Use docs OG routes for site metadata. Use chat `to_social(...)` for analyst-created, one-off share assets.

## Placement rules
- Choose Observable Plot for docs-authored interactive explanation.
- Choose Recharts for docs admin and telemetry dashboards.
- Choose Plotly for chat-first interactive analysis and embeddable figures.
- Choose matplotlib for custom static graphics, especially court and radar visuals.
- Treat shot charts as two separate surfaces: docs demo widget vs chat analysis helper.
- Treat social cards as two separate surfaces: docs metadata image vs chat export artifact.
- Treat embeds as a chat artifact-export feature, not a docs component system.

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/query-cookbook-families|Query Cookbook Families]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| docs chart stack and admin split | `docs/AGENTS.md` | canonical docs-side contract for Observable Plot and Recharts |
| docs MDX chart components | `docs/components/mdx/observable-plot.tsx` | main Observable Plot wrappers plus docs `ShotChart` |
| docs client-only widget loading | `docs/components/mdx/dynamic-charts.tsx` | dynamic import and error boundary behavior |
| docs MDX registration | `docs/components/mdx.tsx` | where docs pages gain access to chart widgets |
| docs shot chart guide usage | `docs/content/docs/start/shot-chart-analysis.mdx` | live `ShotChart` example in authored docs |
| docs query-to-shot-chart handoff | `docs/content/docs/start/analytics-quickstart.mdx` | upstream shot-location query pattern |
| docs admin monitoring charts | `docs/app/(admin)/admin/pipeline/pipeline-charts.tsx` | Recharts-based pipeline dashboard composition |
| docs admin chart wrapper shape | `docs/components/admin/chart-area.tsx` | representative Recharts wrapper |
| docs social card routes | `docs/app/opengraph-image.tsx`, `docs/app/docs-og/{catch-all}/route.tsx` | site-level and page-level OG image generation |
| chat prompt chart policy | `src/nbadb/chat/prompts.py` | Plotly-vs-matplotlib guidance, share helpers, shot-chart routing |
| chat sandbox display and export helpers | `src/nbadb/chat/app/preamble.py` | `chart`, `annotated_chart`, `to_embed`, `to_social`, patched `plt.show()` |
| chat renderer behavior | `chat/chainlit_app.py` | Plotly inline rendering, matplotlib image rendering, export file handling |
| chat skill rules | `chat/skills/analysis-and-visualization/SKILL.md`, `chat/skills/nba-data-analytics/SKILL.md` | chart heuristics, shot-chart lane, export/helper inventory |
| chat helper scripts | `chat/skills/nba-data-analytics/scripts/court.py`, `.../compare.py`, `.../lineups.py`, `src/nbadb/chat/mcp/sandbox.py` | concrete chart-producing runtime helpers and sandbox exposure |
