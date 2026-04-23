---
title: Query Cookbook Families
tags:
  - kb
  - topics
  - analytics
  - sql
  - cookbook
aliases:
  - NBA Query Cookbook Families
kind: concept
status: active
updated: 2026-04-14
source_count: 4
---

# Query Cookbook Families

This note groups `references/query-cookbook.md` into the main analysis families it supports so you can route a question to the right SQL shape faster.

## Family map
| Family | Cookbook sections | Best starting surface | Core shape |
| --- | --- | --- | --- |
| Season-over-season deltas | Year-over-Year Stat Changes | `agg_player_season` + `dim_player` | `LAG()` over player-season partitions |
| Rolling game trends | 10-Game Rolling Averages | `fact_player_game_log` + `dim_game` + `dim_player` | window functions over ordered game dates |
| Matchup lookups | Head-to-Head Matchup Query | `analytics_head_to_head` first | paired team filters and game outcomes |
| Threshold detection | Triple-Double Detection | `fact_player_game_log` + `dim_game` + `dim_player` | CASE-based stat counting |
| Efficiency plotting inputs | Efficiency Scatterplot Data | `agg_player_season` + `dim_player` + `dim_team` | derive efficiency and volume fields |
| Shot geography | Shot Chart Data Pull | `fact_shot_chart_detail` + `dim_player` | `loc_x` / `loc_y` plus shot-zone fields |
| Group impact | Lineup Efficiency; On/Off Impact | `agg_lineup_efficiency`; `agg_on_off_splits` | rank groups or compare splits |

## Working rules that show up across families
Keep these pins explicit unless the question is intentionally open-ended:
- `season_year`
- `season_type`
- minimum games or minutes thresholds
- `p.is_current = TRUE` on `dim_player` joins

## When the cookbook leaves pure SQL
The cookbook is SQL-first, but several families are designed to continue in Python for plotting, shot charts, and lineup helpers.

## Related notes
- [[wiki/topics/query-patterns|Query Patterns]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/chat-surface|Chat Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| cookbook family list and example SQL shapes | `chat/skills/nba-data-analytics/references/query-cookbook.md` | canonical query examples |
| allowed tools and table-selection rules | `chat/skills/nba-data-analytics/SKILL.md` | skill contract |
| pinning guidance and analytics-first routing | `wiki/topics/query-patterns.md` | existing KB shorthand |
| relationship to analytics skill | `wiki/topics/analytics-skill-guide.md` | existing KB context note |
