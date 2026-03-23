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

## Complex Query Patterns

For multi-season comparisons, rolling averages, pivot tables, head-to-head matchups, and efficiency queries, use `read_file` on `references/query-cookbook.md` in this skill directory.
