---
title: Comparison And Similarity Helpers
tags:
  - kb
  - topics
  - analytics
  - chat
  - comparison
  - similarity
aliases:
  - compare.py Surface
  - similarity.py Surface
  - Player Comparison Helpers
  - Player Similarity Helpers
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Comparison And Similarity Helpers

This note covers the chat-side helper modules `compare.py` and `similarity.py` under the NBA analytics skill.

They are pandas-first post-query helpers that live inside the chat Python sandbox. They are meant to shape, normalize, compare, and visualize already-retrieved player datasets, not to replace SQL table selection, joins, or warehouse aggregation.

## Runtime surface
- `chat/server/_preamble.py` inserts the skill `scripts/` directory onto `sys.path` and imports both modules directly as `compare` and `similarity`.
- The `run_python` sandbox therefore exposes them as built-in helper surfaces during chat analysis.
- The analytics skill documents both surfaces explicitly, so they are part of the intended public chat-analysis contract rather than incidental utility code.
- Both modules are local, in-memory helpers: they operate on DataFrames or dict-like inputs and do not persist state, hit the network, or execute SQL themselves.

## `compare.py`

### Best-fit questions
- Compare a small set of players side by side on the same stat columns.
- Add percentile context for a player pool after the pool has already been selected.
- Normalize box-score stats to per-36 or per-100 rates before discussion.
- Produce a compact radar chart after the comparison frame is ready.

### Helper surface
| Function | Input expectation | Output shape | Best fit |
|----------|-------------------|--------------|----------|
| `compare.compare_players(df, player_col='full_name', metrics=None)` | One row per player, with numeric stat columns | DataFrame indexed by player plus a `League Avg` row | Side-by-side summary table |
| `compare.percentile_rank(df, player_col='full_name', metrics=None, ascending_cols=None)` | One row per player with comparable numeric columns | DataFrame with `*_pctile` columns | Ranking players within a selected cohort |
| `compare.radar_chart(player_stats, categories=None, title='', max_values=None)` | Dict-of-dicts or DataFrame already limited to a few players and metrics | Matplotlib `Figure` | Presentation-oriented comparison chart |
| `compare.per36(df, min_col='avg_min', stat_cols=None)` | DataFrame with a minutes column and counting stats | Same DataFrame plus `*_per36` columns | Minute-normalized player comparisons |
| `compare.per100(df, pace_col='pace', stat_cols=None)` | DataFrame with a pace-like possessions column and counting stats | Same DataFrame plus `*_per100` columns | Possession-normalized comparisons |

### Behavioral notes
- `compare_players` auto-detects numeric metrics and excludes `player_id` by default.
- `percentile_rank` supports lower-is-better metrics through `ascending_cols`, which is the hook for stats such as turnovers or fouls.
- `radar_chart` is defensive: empty input returns a placeholder figure, and fewer than three categories yields a figure with a message instead of failing.
- `per36` and `per100` preserve the original columns and write additive normalized columns, returning `0.0` when the denominator column is zero.

## `similarity.py`

### Best-fit questions
- Find statistical comps for a player from one season snapshot.
- Group a player pool into rough archetypes.
- Compare career arcs aligned by age rather than by raw totals.

### Helper surface
| Function | Input expectation | Output shape | Best fit |
|----------|-------------------|--------------|----------|
| `similarity.normalize_stats(df, metrics)` | DataFrame plus explicit metric list | Same DataFrame with z-scored metric columns | Internal prep step for scale-free comparisons |
| `similarity.find_similar(df, target_name, player_col='full_name', metrics=None, n=10, method='cosine')` | One row per player with a named target present | Ranked DataFrame with `similarity` plus original metrics | Single-season player comps |
| `similarity.cluster_players(df, player_col='full_name', metrics=None, n_clusters=5)` | One row per player with numeric metrics | Same DataFrame plus `cluster` | Archetype grouping or segmentation |
| `similarity.career_similarity(df_seasons, target_name, player_col='full_name', age_col='age', metrics=None, n=10)` | Multi-row-per-player seasonal history aligned by age or stage | Ranked DataFrame with `similarity` and `seasons_compared` | Career-trajectory comps |

### Behavioral notes
- `normalize_stats` uses z-score normalization and zeros out constant columns.
- `find_similar` drops rows with missing metric values, returns an error DataFrame if the target is absent, and supports `cosine` or `euclidean` scoring.
- `find_similar` merges the winning rows back to the original metric columns so the result is immediately explainable in chat.
- `cluster_players` prefers SciPy k-means, but falls back to quantile bucketing on the first metric if SciPy clustering is unavailable.
- `career_similarity` only compares overlapping ages and requires at least two shared ages, which keeps it focused on trajectory overlap rather than loose career totals.

## Where they fit in the chat analysis flow
These helpers belong in the Python post-processing step, not the warehouse-retrieval step.

Typical flow:
1. Use the chat agent prompt and analytics skill guidance to choose the right warehouse surface.
2. Retrieve the base dataset with `run_sql` or `query(...)`.
3. Refine inside `run_python`, often starting from `last_result`.
4. Apply `compare.*` when the task is side-by-side framing, percentile context, or normalization for presentation.
5. Apply `similarity.*` when the task is nearest-neighbor comps, archetype grouping, or aligned career-arc matching.
6. Render the final output with `table(df)`, `show(data)`, or a chart helper.

That placement matches the system prompt's workflow: retrieval first, then Python for post-processing and charting after the data shape is correct.

## Boundaries and intended use
- Prefer SQL first for filtering, joins, aggregation, and cohort definition.
- Use `compare.py` once the player set is already correct and the ask becomes comparative framing or normalization.
- Use `similarity.py` once the feature columns are already assembled and the ask becomes profile matching or clustering.
- These modules are player-analysis helpers, not general warehouse APIs.
- `compare.radar_chart` is the presentation surface here; most other functions return DataFrames meant to be passed to `table(...)` or used in a follow-up chart.

## Related notes
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/metric-calculator-surface|Metric Calculator Surface]]
- [[wiki/topics/lineup-trend-helpers|Lineup And Trend Helpers]]
- [[wiki/topics/visualization-surface|Visualization Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| runtime pre-import of `compare` and `similarity` into chat Python | `/Users/ww/dev/projects/nbadb/chat/server/_preamble.py` | canonical runtime loading path |
| `run_python` sandbox contract and built-in helper framing | `/Users/ww/dev/projects/nbadb/chat/mcp_servers/sandbox.py` | public MCP tool description |
| chat workflow places Python after retrieval for post-processing and charting | `/Users/ww/dev/projects/nbadb/src/nbadb/chat/prompts.py` | system prompt workflow contract |
| documented public `compare.*` and `similarity.*` surfaces | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/SKILL.md` | skill-level contract and intended use |
| canonical implementation of comparison helpers | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/scripts/compare.py` | source of function behavior and defaults |
| canonical implementation of similarity helpers | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/scripts/similarity.py` | source of function behavior and defaults |
| verified compare helper output shapes and edge cases | `/Users/ww/dev/projects/nbadb/tests/unit/chat/test_compare.py` | confirms additive columns, percentile logic, and radar-chart fallbacks |
| verified similarity helper output shapes and edge cases | `/Users/ww/dev/projects/nbadb/tests/unit/chat/test_similarity.py` | confirms not-found errors, clustering fallback, and career-overlap rules |
