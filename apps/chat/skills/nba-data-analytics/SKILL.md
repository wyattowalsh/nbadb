---
name: nba-data-analytics
description: >-
  Use when analyzing NBA basketball data, querying the nbadb DuckDB
  database, creating visualizations, or calculating basketball metrics.
---

# NBA Data Analytics Skill

You have access to a comprehensive NBA database via the `run_sql` tool. The database follows a star schema with dimensions, facts, and pre-aggregated rollups.

## Database Schema

### Naming Conventions

- `dim_*` — 17 dimension tables (players, teams, seasons, arenas, coaches, etc.)
- `fact_*` — 102 fact tables (box scores, player tracking, shot charts, matchups, etc.)
- `agg_*` — 16 pre-aggregated rollups (player/team season summaries)
- `analytics_*` — 4 wide analytics views for common queries

### Key Dimensions

- `dim_player` — SCD Type 2 (has `is_current`, `valid_from`, `valid_to`). Always filter `WHERE is_current = TRUE` for current data.
- `dim_team` — Team metadata (abbreviation, city, arena, conference, division)
- `dim_season` — Season metadata (season_id, start/end dates)

### Common Fact Tables

- `fact_player_game_log` — Per-game player stats
- `fact_box_score_*` — Team-level box scores (traditional, advanced, hustle, etc.)
- `fact_player_career` — Career aggregates
- `fact_standings` — Team standings
- `fact_shot_chart_*` — Shot location data

### Pre-Aggregated Tables

- `agg_player_season` — Player stats aggregated by season
- `agg_team_season` — Team stats aggregated by season

## Tools Available

1. **`run_sql`** — Execute DuckDB SQL against the NBA database. Always use this for data queries.
2. **`list_tables`** — List all tables in the database.
3. **`describe_table`** — Get column names and types for a table.
4. **`execute`** — Run Python code to create visualizations or compute metrics.

## DuckDB SQL Tips

- Use `QUALIFY ROW_NUMBER() OVER (...)` for deduplication instead of subqueries
- Use `IS DISTINCT FROM` for NULL-safe comparisons
- JOINs: always join dimensions on their primary key (`player_id`, `team_id`, etc.)
- For current player data: `JOIN dim_player p ON ... AND p.is_current = TRUE`
- DuckDB supports `COLUMNS(regex)`, `EXCLUDE`, `REPLACE` for column selection
- Use `ROUND(value, 1)` for display-friendly numbers

## Visualization Guidelines

When creating charts, use the `execute` tool to run Python with plotly:

- **Bar chart**: comparisons (top scorers, team rankings, stat leaders)
- **Line chart**: trends over time (career arcs, season averages, team performance)
- **Scatter plot**: correlations (PER vs usage, TS% vs volume, off/def rating)
- **Heatmap**: shot charts, game-by-game performance matrices

Always:
1. Import `plotly.express as px` or `plotly.graph_objects as go`
2. Create the figure with clear titles, axis labels, and formatting
3. Call `fig.to_json()` at the end and print the result
4. Use team colors when applicable

## Common NBA Metrics

When users ask about advanced metrics, compute them correctly:

- **PER** (Player Efficiency Rating): comprehensive per-minute rating
- **TS%** (True Shooting): `pts / (2 * (fga + 0.44 * fta))`
- **eFG%** (Effective FG%): `(fgm + 0.5 * fg3m) / fga`
- **Usage Rate**: `100 * ((fga + 0.44 * fta + tov) * (team_min / 5)) / (min * (team_fga + 0.44 * team_fta + team_tov))`
- **Pace**: possessions per 48 minutes
- **Offensive/Defensive Rating**: points scored/allowed per 100 possessions
- **Win Shares**: estimate of wins contributed

## Example Workflows

### "Who scored the most points last season?"
1. `run_sql`: `SELECT p.full_name, s.total_pts FROM agg_player_season s JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE ORDER BY s.total_pts DESC LIMIT 10`
2. Display results as a table

### "Show me a chart of the top 10 scorers"
1. Query the data with `run_sql`
2. Use `execute` to create a Plotly bar chart
3. Return the chart

### "Compare LeBron and Curry's career trajectories"
1. Query career stats by season for both players
2. Use `execute` to create a multi-line Plotly chart
3. Add annotations for key milestones
