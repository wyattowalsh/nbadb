---
title: Query Patterns
tags:
  - kb
  - topics
  - analytics
  - sql
aliases:
  - NBA Query Patterns
kind: concept
status: active
updated: 2026-04-14
source_count: 2
---

# Query Patterns

Use this note as the short menu of reusable SQL shapes for nbadb.

## Always pin
- `season_year`
- `season_type`
- minimum games or minutes
- `p.is_current = TRUE` on SCD2 joins

## Pattern menu
| Pattern | Use when | Start surface |
| --- | --- | --- |
| Year-over-year deltas | Season-over-season change | `agg_player_season` + `LAG()` |
| Rolling windows | Last N games | `fact_player_game_log` + window functions |
| Head-to-head | One matchup pack | `analytics_head_to_head` first |
| Triple-doubles | All-around game detection | `fact_player_game_log` |
| TS% vs volume | Efficiency scatter inputs | `agg_player_season` |
| Shot chart pulls | Court-map data | `fact_shot_chart` or `fact_shot_chart_detail` |
| Lineup / on-off | Combo or impact analysis | `agg_lineup_efficiency`, `agg_on_off_splits` |

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| SQL pattern menu | `chat/skills/nba-data-analytics/references/query-cookbook.md` | reusable example queries |
| surface hints | `chat/skills/nba-data-analytics/references/schema-guide.md` | table-selection hints |
