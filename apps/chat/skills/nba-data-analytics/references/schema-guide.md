# NBA Database Schema Guide

Use `list_tables` and `describe_table` MCP tools at runtime to explore the
full schema interactively. The summary below covers the most common tables.

## Dimension Tables (`dim_*`) — 17

| Table | Description |
|-------|-------------|
| `dim_player` | SCD2 — filter `is_current = TRUE` for latest record |
| `dim_team` | Abbreviation, city, arena, conference, division |
| `dim_season` | Season metadata (season_id, start/end dates) |
| `dim_game` | Game-level metadata (date, home/away, result) |
| `dim_arena` | Arena name, city, capacity |
| `dim_coach` | Head coach per team-season |
| `dim_college` | College/university reference |
| `dim_date` | Calendar date dimension |
| `dim_draft` | Draft pick history |
| `dim_official` | Referee reference |
| `dim_play_event_type` | Play-by-play event types |
| `dim_position` | Player position reference |
| `dim_season_phase` | Regular season, playoffs, all-star |
| `dim_season_week` | Week-by-week breakdown |
| `dim_shot_zone` | Shot chart zone definitions |
| `dim_team_extended` | Extended team info |
| `dim_team_history` | SCD2 franchise history |

## Fact Tables (`fact_*`) — 118

### Box Scores
- `fact_player_game_log` — Per-game player stats (the most common starting point)
- `fact_box_score_traditional` — Traditional team box score
- `fact_box_score_advanced` — Advanced team box score (ORtg, DRtg, pace, TS%)
- `fact_box_score_hustle` — Hustle stats (deflections, charges, contested shots)
- `fact_box_score_misc` — Miscellaneous (points off TO, 2nd chance, fast break)
- `fact_box_score_scoring` — Scoring breakdown (% assisted, % unassisted)
- `fact_box_score_starter_bench` — Starter vs bench splits
- `fact_box_score_team` — Team-level totals

### Player Tracking
- `fact_player_tracking_speed` — Speed/distance
- `fact_player_tracking_touches` — Touches, paint touches, elbow touches
- `fact_player_pt_tracking` — Pass tracking (pass_made, pass_received)

### Shot Data
- `fact_shot_chart_detail` — Individual shot locations (x, y coordinates)

### Standings & Schedule
- `fact_standings` — Team standings by date
- `fact_player_career` — Career stats (8 career types via UNION ALL)

## Pre-Aggregated Tables (`agg_*`) — 16

| Table | Grain | Key Columns |
|-------|-------|-------------|
| `agg_player_season` | player × season | `total_pts`, `avg_pts`, `gp`, `fg_pct`, `avg_ts_pct` |
| `agg_team_season` | team × season | Team totals and averages |
| `agg_player_career` | player career | Career aggregates |
| `agg_player_rolling` | player rolling window | Rolling averages |
| `agg_on_off_splits` | player on/off | Plus-minus with player on/off court |
| `agg_clutch_stats` | player clutch | Last 5 min, score within 5 |
| `agg_league_leaders` | league-wide | League leader boards |
| `agg_lineup_efficiency` | lineup | 5-man lineup stats |

## Analytics Views (`analytics_*`) — 8

Pre-joined wide tables for common queries:

- `analytics_player_game_complete` — Player game log + all box score types
- `analytics_team_season_summary` — Team season overview
- `analytics_clutch_performance` — Clutch performance analysis
- `analytics_head_to_head` — Team head-to-head matchups
- `analytics_player_matchup` — Player vs player matchups
- `analytics_player_season_complete` — Full player season view
- `analytics_shooting_efficiency` — Shooting efficiency breakdowns
- `analytics_team_game_complete` — Team game + all box score types

## Common Join Patterns

```sql
-- Player stats with name (SCD2-safe)
SELECT p.full_name, s.*
FROM agg_player_season s
JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE

-- Last season filter
WHERE s.season_year = (SELECT MAX(season_year) FROM agg_player_season)

-- Game details
SELECT g.game_date, t.abbreviation, f.*
FROM fact_player_game_log f
JOIN dim_game g ON f.game_id = g.game_id
JOIN dim_team t ON f.team_id = t.team_id
```
