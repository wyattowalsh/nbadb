---
title: Lineup And Trend Helpers
tags:
  - kb
  - topics
  - analytics
  - chat
  - lineups
  - trends
aliases:
  - lineups.py Surface
  - trends.py Surface
  - Lineup Analysis Helpers
  - Trend Detection Helpers
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Lineup And Trend Helpers

This note covers the chat-side helper modules `lineups.py` and `trends.py` under the NBA analytics skill.

They are small pandas-first post-query helpers, pre-imported into the `run_python` sandbox, and meant to sit after SQL retrieval rather than replace SQL.

## Runtime surface
- Both modules are loaded by `chat/server/_preamble.py`, so chat Python runs can call `lineups.*` and `trends.*` directly.
- The skill advertises them as lightweight helper surfaces, not warehouse APIs.
- They are intentionally local and safety-constrained: pure analysis helpers over in-memory data, with no filesystem, network, or database side effects inside the helper modules themselves.

## `lineups.py`

### Intended questions
- Which players have the biggest on/off net rating swing?
- Which two-player combinations look strongest across lineup samples?
- Show the best and worst lineups by net rating or another numeric lineup metric.

### Helper surface
| Function | Input expectation | Output shape | Best fit |
|----------|-------------------|--------------|----------|
| `lineups.on_off_impact(df, entity_col='entity_id', on_off_col='on_off', rating_cols=None, name_col=None)` | On/off split frame with paired `On` and `Off` rows per entity | DataFrame with one row per entity and `{metric}_on`, `{metric}_off`, `{metric}_delta` columns | `agg_on_off_splits` style comparisons |
| `lineups.two_man_combos(df, player_cols=None, net_rating_col='avg_net_rating', min_col='min')` | Lineup-level frame with player columns and a lineup metric | DataFrame with `player_1`, `player_2`, `weighted_net_rating`, `total_minutes`, `lineup_count` | Pair-synergy summaries from lineup rows |
| `lineups.lineup_chart(df, lineup_col='group_id', metric_col='avg_net_rating', n=10, title='')` | Frame with lineup label column and numeric metric column | Plotly `Figure` object with top and bottom N horizontal bars | Analyst-facing chart output |

### Expected data shapes

#### `on_off_impact`
- Assumes a pandas DataFrame already filtered to one entity grain such as player or lineup entity.
- Needs a join key in `entity_col` and an `on_off_col` containing case-insensitive `On` and `Off` values.
- Auto-detects numeric columns when `rating_cols` is omitted, excluding only the entity column.
- Returns an empty DataFrame when no entity has both an `On` row and an `Off` row.
- Optional `name_col` is copied from the `On` rows into the result.

Typical input columns:

```text
entity_id | on_off | net_rating | off_rating | def_rating | min | full_name?
```

Typical output columns:

```text
entity_id | net_rating_on | net_rating_off | net_rating_delta | ... | full_name?
```

#### `two_man_combos`
- Assumes one row per lineup sample, not one row per player.
- If `player_cols` is omitted, it scans for columns whose names start with `player`.
- Every lineup row contributes all 2-player combinations from the non-null player values found in that row.
- Minutes are used as the weighting factor; if total minutes for a pair are zero, the helper falls back to a simple average of lineup ratings.
- Returns a one-column error DataFrame when no player columns can be found.

Typical input columns:

```text
player1 | player2 | player3 | player4? | player5? | avg_net_rating | min
```

Typical output columns:

```text
player_1 | player_2 | weighted_net_rating | total_minutes | lineup_count
```

#### `lineup_chart`
- Expects a lineup identifier column such as `group_id` and a sortable numeric metric.
- Uses top N and bottom N rows from the sorted frame, deduplicates overlap, and colors bars green for non-negative values and red for negative values.
- Returns a Plotly figure, not a DataFrame.

## `trends.py`

### Intended questions
- What does a player's last-10 rolling scoring or rebounding trend look like?
- Is the player on a streak above or below a threshold?
- Which games count as statistical breakouts versus season baseline?
- What does the current pace imply for an 82-game season total?

### Helper surface
| Function | Input expectation | Output shape | Best fit |
|----------|-------------------|--------------|----------|
| `trends.rolling_stats(df, stat_cols, window=10, date_col='game_date')` | Game-log frame with sortable date column and numeric stat columns | Same DataFrame, sorted by date, plus `*_rolling_<window>` columns | Rolling form over player or team logs |
| `trends.detect_streaks(df, stat_col, threshold, direction='above', date_col='game_date')` | Game-log frame with one stat column and date column | DataFrame with streak summaries | Consecutive-game threshold streaks |
| `trends.find_breakouts(df, stat_col, sigma=2.0, min_games=20, date_col='game_date')` | Game-log frame with enough games for baseline | Filtered DataFrame of breakout rows plus `_mean`, `_std`, `_threshold`, `_sigma_above` | Outlier-game detection |
| `trends.season_projection(current_stats, games_played, total_games=82)` | Dict or pandas Series of season totals | Dict with nested `projections` per stat | Pace-based full-season projection |

### Expected data shapes

#### `rolling_stats`
- Assumes one row per game.
- Sorts by `date_col` before computing rolling means.
- Adds one rounded rolling-average column per requested stat that exists in the frame.
- Keeps the original rows and columns.

Typical input columns:

```text
game_date | pts | reb | ast | ...
```

Typical added columns:

```text
pts_rolling_10 | reb_rolling_10 | ast_rolling_10
```

#### `detect_streaks`
- Assumes one row per game ordered by date after internal sorting.
- Treats `direction='above'` as `>= threshold` and any other direction value as `<= threshold`.
- Returns an empty DataFrame with summary columns when no qualifying games exist.
- Output is sorted by longest streak first.

Output columns:

```text
streak_id | start_date | end_date | length | avg_value | max_value
```

#### `find_breakouts`
- Assumes a game-log DataFrame where `stat_col` supports mean and standard deviation.
- Requires at least `min_games`; otherwise returns `DataFrame({'error': [...]})`.
- Uses `mean + sigma * std` as the breakout threshold.
- Returns only qualifying rows, sorted descending by date when `date_col` exists, plus baseline metadata columns prefixed with `_`.

#### `season_projection`
- Expects season totals, not per-game averages.
- Accepts either a plain dict or a pandas Series.
- Returns a dict shaped like:

```python
{
    'games_played': 41,
    'total_games': 82,
    'projections': {
        'pts': {
            'current_total': 1000.0,
            'per_game': 24.39,
            'projected_total': 2000.0,
            'projected_low': 1900.0,
            'projected_high': 2100.0,
        }
    }
}
```

- Returns `{'error': 'No games played'}` when `games_played <= 0`.

## Usage pattern
1. Pull a base dataset with `query(...)` from the warehouse.
2. Use `lineups.*` or `trends.*` in `run_python` for post-query shaping.
3. Render the result as a table or chart.

The query cookbook explicitly shows `agg_on_off_splits` followed by `lineups.on_off_impact(...)`, which is the clearest intended handoff pattern for these helpers.

## Boundaries
- Prefer SQL first for filtering, joins, and aggregation.
- Use these helpers when the ask becomes row-wise post-processing, rolling-window calculation, streak extraction, pair expansion, or chart shaping.
- `lineup_chart` is the only visualization helper here; the rest return DataFrames or plain dicts.
- `trends.find_breakouts` is the DataFrame workflow; scalar or list-based breakout summaries belong to `nba_stats.breakout_threshold`, not this module.

## Related notes
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/query-cookbook-families|Query Cookbook Families]]
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/metric-calculator-surface|Metric Calculator Surface]]

## Provenance
| Claim or section | Local repo path | Notes |
|------------------|-----------------|-------|
| runtime pre-import of `lineups` and `trends` into chat Python | `/Users/ww/dev/projects/nbadb/chat/server/_preamble.py` | canonical runtime loading path |
| advertised public helper surface and intended table families | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/SKILL.md` | skill-level contract |
| `lineups.on_off_impact`, `two_man_combos`, and `lineup_chart` behavior | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/scripts/lineups.py` | canonical implementation |
| `trends.rolling_stats`, `detect_streaks`, `find_breakouts`, and `season_projection` behavior | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/scripts/trends.py` | canonical implementation |
| intended SQL-to-helper handoff for on/off analysis | `/Users/ww/dev/projects/nbadb/chat/skills/nba-data-analytics/references/query-cookbook.md` | shows explicit `query(...)` then `lineups.on_off_impact(...)` pattern |
| helper inventory and data-shape bias summary | `/Users/ww/dev/projects/nbadb/kb/raw/extracts/internal/analytics-helper-surface-manifest.md` | repo-local extract already summarizing the helper set |
| verified lineup helper result shapes and edge cases | `/Users/ww/dev/projects/nbadb/tests/unit/chat/test_lineups.py` | empty result, name column, pair output, Plotly figure expectations |
| verified trend helper result shapes and edge cases | `/Users/ww/dev/projects/nbadb/tests/unit/chat/test_trends.py` | rolling columns, empty streak result, breakout error path, projection dict shape |
