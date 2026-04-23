---
title: Court Helper Internals
tags:
  - kb
  - topics
  - chat
  - visualization
  - skills
  - shot-chart
aliases:
  - Shot Chart Helper Internals
  - Court Script Internals
kind: concept
status: active
updated: 2026-04-14
source_count: 7
---

# Court Helper Internals

`chat/skills/nba-data-analytics/scripts/court.py` is the chat-side matplotlib helper for NBA half-court visuals. It is built for the `run_python` sandbox, not for docs MDX widgets or generic interactive Plotly work.

## What the module owns
| Function | Primary input shape | Output | Main use |
| --- | --- | --- | --- |
| `draw_court` | optional matplotlib `Axes` | configured half-court axes | reusable court geometry |
| `shot_chart` | shot-level rows with `loc_x`, `loc_y`, `shot_made_flag` | static scatter chart | makes vs misses |
| `shot_heatmap` | shot-level rows with `loc_x`, `loc_y` | static hexbin chart | shot density |
| `zone_chart` | zone-level aggregate rows | static annotated court | FG% vs league average |
| `compare_shots` | two shot-level DataFrames | two-panel static chart | side-by-side density comparison |

## Coordinate and drawing model
- The helper assumes NBA half-court coordinates in tenths of a foot.
- The visible court window is `x = [-250, 250]` and `y = [-50, 420]`.
- `draw_court(...)` is the shared primitive. Every higher-level chart calls it first.
- Court geometry is assembled from matplotlib `Circle`, `Arc`, `Rectangle`, and `Line2D` patches.
- `_BG_COLOR` is a fixed dark background (`#141a2e`) used for newly created figures and legends.
- `_ZONE_CENTROIDS` is a hard-coded lookup from `(zone_basic, zone_area)` to label positions for `zone_chart(...)`.

## Runtime contract in chat
- The sandbox preamble prepends `chat/skills/nba-data-analytics/scripts` to `sys.path` and pre-imports `court`.
- `matplotlib` is forced onto the `Agg` backend before user code runs.
- `plt.show()` is monkey-patched to serialize the current figure as base64 PNG and close all figures.
- Because of that patch, the court helpers deliberately call `plt.show()` themselves and still return the `Figure` for optional reuse.
- These helpers expect a pandas-like DataFrame contract. They do not validate columns, types, or coordinate ranges before plotting.

## Function-level behavior

### `draw_court(...)`
- Creates a new `(12, 11)` figure only when no axes are supplied.
- Draws hoop, backboard, paint, free-throw arcs, restricted arc, three-point arc, corner lines, center arc, and half-court line.
- Sets equal aspect ratio and hides axes.
- `outer_lines=True` adds the boundary rectangle; the default chart helpers leave it off.

### `shot_chart(...)`
- Splits the input into made and missed subsets using `shot_made_flag == 1` and `== 0`.
- Uses green circles for makes and red `x` markers for misses.
- Only adds a legend when the DataFrame is non-empty.
- Best fit: shot-detail pulls where each row is a single attempt.

### `shot_heatmap(...)`
- Uses `ax.hexbin(...)` with `cmap="YlOrRd"`, `mincnt=1`, and a configurable `gridsize` via `bins`.
- Adds a matplotlib colorbar labeled `Shot count`.
- Best fit: density views where makes vs misses do not matter.

### `zone_chart(...)`
- Expects one row per zone, not one row per shot.
- Looks up the plotting position from `_ZONE_CENTROIDS`; unknown zone pairs are skipped silently.
- Compares `fg_pct` against `league_avg_fg_pct` and colors the zone green when at or above average, red otherwise.
- Uses fixed-size circles, so color and text carry the message rather than area.

### `compare_shots(...)`
- Builds a two-panel layout and reuses the same heatmap recipe on each side.
- Calls `draw_court(ax)` for both subplots.
- Adds a separate colorbar to each subplot, which keeps each panel readable but makes cross-panel color intensity only loosely comparable.

## Prompt and skill handoff
- `chat/server/prompts.py` is only a compatibility wrapper; the canonical prompt text lives in `src/nbadb/chat/prompts.py`.
- The shared system prompt says to retrieve data first and then use Python for post-processing, charting, and artifacts.
- The `Visualization` profile strengthens that rule by asking for a chart whenever the data shape supports it.
- The `nba-data-analytics` skill is the concrete contract that names `court.draw_court`, `court.shot_chart`, `court.shot_heatmap`, `court.zone_chart`, and `court.compare_shots` as supported helpers inside `run_python`.
- The query cookbook shows the expected workflow: pull shot-location rows in SQL, then call a `court.*` function in Python.

## Data-surface note
- The skill summary uses `fact_shot_chart` as shorthand for shot-location work.
- The concrete reference material points at `fact_shot_chart_detail` for actual shot-detail queries.
- When writing or debugging examples, follow the cookbook and schema guide surface names first.

## Use it when
- You need a static half-court artifact in chat.
- You need shot-location geometry that is easier in matplotlib than Plotly.
- You are comparing two players' spatial shot distributions side by side.
- You already have shot-detail or zone-aggregate rows in a pandas DataFrame.

## Prefer something else when
- You want hover, zoom, or richer interactivity. Use Plotly helpers instead.
- You are authoring docs-site content. Use the docs visualization components, not the chat sandbox helper.
- You need validation, normalization, or SQL assembly. The court module only plots the data it is given.

## Related notes
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-cookbook-families|Query Cookbook Families]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
| --- | --- | --- |
| module ownership, dimensions, zone centroids, plotting behavior | `chat/skills/nba-data-analytics/scripts/court.py` | canonical helper implementation |
| sandbox import wiring and patched `plt.show()` behavior | `chat/server/_preamble.py` | explains why `court.*` emits PNG output directly |
| `run_python` tool contract and skills-dir injection | `chat/mcp_servers/sandbox.py` | concrete chat runtime exposure |
| court helper API listed in the skill | `chat/skills/nba-data-analytics/SKILL.md` | user-facing helper contract |
| shot-chart SQL-to-Python workflow example | `chat/skills/nba-data-analytics/references/query-cookbook.md` | concrete usage pattern |
| shot-detail table naming and common schema summary | `chat/skills/nba-data-analytics/references/schema-guide.md` | reference surface for real queries |
| prompt workflow and visualization profile; wrapper indirection | `chat/server/prompts.py`, `src/nbadb/chat/prompts.py` | wrapper path plus canonical prompt text |
