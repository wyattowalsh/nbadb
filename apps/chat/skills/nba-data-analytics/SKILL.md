---
name: nba-data-analytics
description: >-
  Use when NBA queries require multi-table star schema joins, SCD2 dimension
  handling, advanced metric formulas (TS%, eFG%, usage rate), or Plotly
  chart generation against the nbadb DuckDB database.
allowed_tools:
  - run_sql
  - list_tables
  - describe_table
  - run_python
---

# NBA Data Analytics Skill

## Metric Calculator API

The `run_python` tool pre-imports `metric_calculator as mc`. Call directly:

| Function | Signature | Notes |
|----------|-----------|-------|
| `mc.true_shooting_pct` | `(pts, fga, fta)` | TS% = pts / (2 * (fga + 0.44 * fta)) |
| `mc.effective_fg_pct` | `(fgm, fg3m, fga)` | eFG% = (fgm + 0.5 * fg3m) / fga |
| `mc.usage_rate` | `(fga, fta, tov, min, team_fga, team_fta, team_tov, team_min)` | Requires both player and team stats |
| `mc.pace` | `(team_poss, opp_poss, team_min)` | Possessions per 48 minutes |
| `mc.offensive_rating` | `(pts, possessions)` | Points per 100 possessions |
| `mc.defensive_rating` | `(opp_pts, possessions)` | Points allowed per 100 possessions |
| `mc.net_rating` | `(off_rating, def_rating)` | ORtg - DRtg |
| `mc.assist_to_turnover` | `(ast, tov)` | Returns None if tov=0 |
| `mc.rebound_pct` | `(reb, min, team_reb, opp_reb, team_min)` | Player's share of available rebounds |

Additional metrics:

| Function | Signature | Notes |
|----------|-----------|-------|
| `mc.game_score` | `(pts, fgm, fga, ftm, fta, oreb, dreb, stl, ast, blk, pf, tov)` | Hollinger's Game Score |
| `mc.possessions` | `(fga, fta, oreb, tov)` | Estimated possessions from box score |
| `mc.per_minute` | `(stat, minutes, base=36)` | Per-36 (or per-48) normalization |
| `mc.assist_pct` | `(ast, min, team_fgm, fgm, team_min)` | % of teammate FG assisted |
| `mc.steal_pct` | `(stl, min, team_poss, team_min)` | Steals per possession on floor |
| `mc.block_pct` | `(blk, min, opp_fga, team_min)` | Blocks per opponent FGA on floor |
| `mc.turnover_pct` | `(tov, fga, fta)` | Turnovers per play |

All functions accept `None` (coerced to 0.0) and guard against division by zero.

**PER / Win Shares**: NOT pre-computed. Require league averages not available in this database. Only compute approximations when the user understands the limitations.

## Table Selection

1. **Simple player stats** → `agg_player_season` (pre-aggregated)
2. **Game-by-game** → `fact_player_game_log` or `analytics_player_game_complete` (pre-joined)
3. **Team season overview** → `analytics_team_season_summary` (pre-joined)
4. **Shot locations** → `fact_shot_chart_detail` (x/y coordinates)
5. **Clutch stats** → `analytics_clutch_performance` (pre-joined)
6. **Head-to-head** → `analytics_head_to_head` (pre-joined)
7. **Player tracking** → `fact_player_tracking_*` (speed, touches, passes)
8. **Need specific columns** → `describe_table` first, then direct `fact_*` query

Always prefer `analytics_*` views — they pre-join dimensions and save query complexity.

## SCD2 Gotchas

- `dim_player` has multiple rows per player (historical team changes). ALWAYS filter `is_current = TRUE` unless analyzing trade history.
- `dim_team_history` is also SCD2. Use `is_current = TRUE` for current franchise info.
- When counting distinct players, use `DISTINCT player_id` NOT `DISTINCT full_name` (name collisions exist).

## Team Colors for Charts

The `run_python` tool can import `team_colors`:

```python
from team_colors import get_team_color, get_color_map
color_map = get_color_map(["LAL", "BOS", "GSW"])
fig = px.bar(..., color_discrete_map=color_map)
```

## Display & Export Helpers

The `run_python` sandbox provides these additional helpers:

| Helper | Purpose |
|--------|---------|
| `table(df)` | Display DataFrame (auto-saves as `last_result`) |
| `chart(fig)` | Display Plotly figure |
| `show(data)` | Auto-detect: Plotly → chart, DataFrame → table |
| `annotated_chart(fig, df, col)` | Chart with average reference line |
| `to_csv(df, name)` | Export as downloadable CSV |
| `to_xlsx(df, name)` | Export as downloadable XLSX |
| `to_json(df, name)` | Export as downloadable JSON |
| `to_spreadsheet(df, name)` | Editable HTML spreadsheet (AG Grid) |
| `to_embed(fig, title)` | Self-contained HTML for blog embedding |
| `to_social(df, headline)` | 1200x630 branded PNG card |
| `to_thread(insights)` | Numbered thread for social media |

## Session State

`last_result` holds the DataFrame from the previous tool call. Use it for iterative refinement:

```python
# After a query that returned player stats:
df = last_result[last_result['age'] < 25]  # filter
df['ts_pct'] = df.apply(lambda r: mc.true_shooting_pct(r['pts'], r['fga'], r['fta']), axis=1)
table(df)  # display and save as new last_result
```

## Shot Chart Visualization (`court`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `court.draw_court` | `(ax=None, color='white', lw=1.5)` | Draw NBA half-court diagram |
| `court.shot_chart` | `(df, x='loc_x', y='loc_y', made='shot_made_flag')` | Scatter plot on court |
| `court.shot_heatmap` | `(df, x='loc_x', y='loc_y', bins=25)` | Hexbin heatmap on court |
| `court.zone_chart` | `(df, zone='zone_basic', area='zone_area', fg_pct='fg_pct')` | Zone FG% coloring |
| `court.compare_shots` | `(df1, df2, name1, name2)` | Side-by-side court plots |

Uses `fact_shot_chart_detail` which has `loc_x`, `loc_y`, `shot_made_flag`, `zone_basic`, `zone_area`.

## Player Comparison (`compare`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `compare.compare_players` | `(df, player_col='full_name', metrics=None)` | Side-by-side table + league avg |
| `compare.percentile_rank` | `(df, player_col, metrics=None, ascending_cols=None)` | 0-100 percentile rankings |
| `compare.radar_chart` | `(player_stats, categories=None, title='')` | Radar/spider chart (up to 5 players) |
| `compare.per36` | `(df, min_col='avg_min', stat_cols=None)` | Per-36-minute normalization |
| `compare.per100` | `(df, pace_col='pace', stat_cols=None)` | Per-100-possession normalization |

`radar_chart` accepts dict `{player: {metric: value}}` or DataFrame. Uses team colors when available.

## Statistical Testing (`nba_stats`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `nba_stats.is_significant` | `(group_a, group_b, test='auto', alpha=0.05)` | Auto-selects t-test or Mann-Whitney |
| `nba_stats.shooting_confidence` | `(makes, attempts, confidence=0.95)` | Wilson score interval for FG% |
| `nba_stats.breakout_threshold` | `(series, sigma=2.0)` | Find outlier games N sigma above mean |
| `nba_stats.streak_significance` | `(outcomes, direction='hot')` | Runs test for streak clustering |

All return JSON-serializable dicts with `summary` key for natural language output.

## Player Similarity (`similarity`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `similarity.find_similar` | `(df, target_name, player_col='full_name', n=10, method='cosine')` | N most similar players |
| `similarity.cluster_players` | `(df, player_col, metrics=None, n_clusters=5)` | K-means clustering |
| `similarity.career_similarity` | `(df_seasons, target_name, player_col, age_col='age', n=10)` | Career trajectory similarity |

Uses z-score normalization + cosine or euclidean distance. Useful for draft comps, trade targets.

## Lineup Analysis (`lineups`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `lineups.on_off_impact` | `(df, entity_col, on_off_col, rating_cols=None)` | On/off court rating deltas |
| `lineups.two_man_combos` | `(df, player_cols, net_rating_col, min_col)` | All 2-player combo stats |
| `lineups.lineup_chart` | `(df, lineup_col, metric_col, n=10)` | Top/bottom lineup bar chart |

Works with `agg_lineup_efficiency` and `agg_on_off_splits` tables.

## Trend & Streak Detection (`trends`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `trends.rolling_stats` | `(df, stat_cols, window=10, date_col='game_date')` | Custom rolling averages |
| `trends.detect_streaks` | `(df, stat_col, threshold, direction='above')` | Consecutive-game streaks |
| `trends.find_breakouts` | `(df, stat_col, sigma=2.0, min_games=20)` | Outlier game detection |
| `trends.season_projection` | `(current_stats, games_played, total_games=82)` | Pace-based 82-game projection + CI |

## Complex Query Patterns

For multi-season comparisons, rolling averages, pivot tables, head-to-head matchups, and efficiency queries, use `read_file` on `references/query-cookbook.md` in this skill directory.
