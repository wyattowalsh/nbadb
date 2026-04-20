# Query Cookbook

Reusable SQL patterns for common NBA analytics queries against the nbadb star schema.

## Year-over-Year Stat Changes

Use `LAG()` to compare a player's stats across consecutive seasons.

```sql
SELECT
    p.full_name,
    s.season_year,
    s.avg_pts,
    s.avg_reb,
    s.avg_ast,
    ROUND(s.avg_pts - LAG(s.avg_pts) OVER (
        PARTITION BY s.player_id ORDER BY s.season_year
    ), 1) AS pts_change,
    ROUND(s.avg_reb - LAG(s.avg_reb) OVER (
        PARTITION BY s.player_id ORDER BY s.season_year
    ), 1) AS reb_change,
    ROUND(s.avg_ast - LAG(s.avg_ast) OVER (
        PARTITION BY s.player_id ORDER BY s.season_year
    ), 1) AS ast_change
FROM agg_player_season s
JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE
WHERE p.full_name = 'Jayson Tatum'
ORDER BY s.season_year
```

## 10-Game Rolling Averages

Compute rolling windows over game logs for trend analysis.

```sql
SELECT
    p.full_name,
    g.game_date,
    f.pts,
    f.reb,
    f.ast,
    ROUND(AVG(f.pts) OVER (
        PARTITION BY f.player_id
        ORDER BY g.game_date
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ), 1) AS rolling_avg_pts,
    ROUND(AVG(f.reb) OVER (
        PARTITION BY f.player_id
        ORDER BY g.game_date
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ), 1) AS rolling_avg_reb,
    ROUND(AVG(f.ast) OVER (
        PARTITION BY f.player_id
        ORDER BY g.game_date
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ), 1) AS rolling_avg_ast
FROM fact_player_game_log f
JOIN dim_player p ON f.player_id = p.player_id AND p.is_current = TRUE
JOIN dim_game g ON f.game_id = g.game_id
WHERE p.full_name = 'Luka Doncic'
  AND g.game_date >= '2025-10-01'
ORDER BY g.game_date
```

## Head-to-Head Matchup Query

Compare two teams' records and stats when they play each other.

```sql
SELECT
    home.abbreviation AS home_team,
    away.abbreviation AS away_team,
    g.game_date,
    g.home_score,
    g.away_score,
    CASE WHEN g.home_score > g.away_score THEN home.abbreviation
         ELSE away.abbreviation END AS winner
FROM dim_game g
JOIN dim_team home ON g.home_team_id = home.team_id
JOIN dim_team away ON g.away_team_id = away.team_id
WHERE home.abbreviation IN ('LAL', 'BOS')
  AND away.abbreviation IN ('LAL', 'BOS')
  AND g.game_date >= '2020-01-01'
ORDER BY g.game_date DESC
```

Or use the pre-joined `analytics_head_to_head` view:

```sql
SELECT *
FROM analytics_head_to_head
WHERE (team_abbreviation = 'LAL' AND opponent_abbreviation = 'BOS')
   OR (team_abbreviation = 'BOS' AND opponent_abbreviation = 'LAL')
ORDER BY game_date DESC
```

## Triple-Double Detection

Find games where a player recorded a triple-double.

```sql
SELECT
    p.full_name,
    g.game_date,
    t.abbreviation AS team,
    f.pts,
    f.reb,
    f.ast,
    f.stl,
    f.blk
FROM fact_player_game_log f
JOIN dim_player p ON f.player_id = p.player_id AND p.is_current = TRUE
JOIN dim_game g ON f.game_id = g.game_id
JOIN dim_team t ON f.team_id = t.team_id
WHERE (CASE WHEN f.pts >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.reb >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.ast >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.stl >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.blk >= 10 THEN 1 ELSE 0 END) >= 3
ORDER BY g.game_date DESC
LIMIT 50
```

Season triple-double leaderboard:

```sql
SELECT
    p.full_name,
    s.season_year,
    COUNT(*) AS triple_doubles
FROM fact_player_game_log f
JOIN dim_player p ON f.player_id = p.player_id AND p.is_current = TRUE
JOIN dim_game g ON f.game_id = g.game_id
JOIN dim_season s ON g.season_id = s.season_id
WHERE (CASE WHEN f.pts >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.reb >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.ast >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.stl >= 10 THEN 1 ELSE 0 END
     + CASE WHEN f.blk >= 10 THEN 1 ELSE 0 END) >= 3
GROUP BY p.full_name, s.season_year
ORDER BY triple_doubles DESC
LIMIT 20
```

## Efficiency Scatterplot Data (TS% vs Usage)

Pull data suitable for a scatter plot correlating shooting efficiency with usage.

```sql
SELECT
    p.full_name,
    t.abbreviation AS team,
    s.gp,
    s.avg_pts,
    s.total_fga,
    s.total_fta,
    s.total_pts,
    ROUND(s.total_pts / NULLIF(2.0 * (s.total_fga + 0.44 * s.total_fta), 0), 3) AS ts_pct,
    ROUND(s.total_fga / NULLIF(s.gp, 0), 1) AS fga_per_game
FROM agg_player_season s
JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE
JOIN dim_team t ON p.team_id = t.team_id
WHERE s.season_year = (
    SELECT MAX(season_year) FROM agg_player_season
    WHERE season_type = 'Regular Season'
)
  AND s.season_type = 'Regular Season'
  AND s.gp >= 40
  AND s.total_fga >= 300
ORDER BY ts_pct DESC
```

Then in `run_python`:

```python
df = query("""<the SQL above>""")
fig = px.scatter(
    df, x="fga_per_game", y="ts_pct",
    text="full_name", size="avg_pts",
    title="True Shooting % vs Volume",
    labels={"fga_per_game": "FGA per Game", "ts_pct": "True Shooting %"},
)
fig.update_traces(textposition="top center", textfont_size=8)
show(fig)
```

## Shot Chart Data Pull

Query shot chart data for visualization with `court.*` functions.

```sql
SELECT
    p.full_name,
    s.loc_x,
    s.loc_y,
    s.shot_made_flag,
    s.shot_type,
    s.zone_basic,
    s.zone_area,
    s.zone_range,
    s.shot_distance
FROM fact_shot_chart_detail s
JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE
WHERE p.full_name = 'Stephen Curry'
  AND s.season_year = (SELECT MAX(season_year) FROM fact_shot_chart_detail)
```

Then in `run_python`:

```python
df = query("""<the SQL above>""")
court.shot_heatmap(df, title="Stephen Curry Shot Chart 2025-26")
```

## Lineup Efficiency

Top 5-man lineups by net rating from `agg_lineup_efficiency`.

```sql
SELECT
    group_id,
    avg_net_rating,
    min,
    gp
FROM agg_lineup_efficiency
WHERE team_id = (SELECT team_id FROM dim_team WHERE abbreviation = 'BOS')
  AND gp >= 10
ORDER BY avg_net_rating DESC
LIMIT 20
```

## On/Off Impact

Player on/off court impact from `agg_on_off_splits`.

```sql
SELECT
    p.full_name,
    s.on_off,
    s.off_rating,
    s.def_rating,
    s.net_rating,
    s.min
FROM agg_on_off_splits s
JOIN dim_player p ON s.entity_id = p.player_id AND p.is_current = TRUE
WHERE s.team_id = (SELECT team_id FROM dim_team WHERE abbreviation = 'BOS')
ORDER BY p.full_name, s.on_off
```

Then in `run_python`:

```python
df = query("""<the SQL above>""")
impact = lineups.on_off_impact(df, entity_col='full_name', on_off_col='on_off',
                                rating_cols=['net_rating'])
table(impact.sort_values('net_rating_delta', ascending=False))
```
