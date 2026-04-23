---
title: Analyst Route
tags:
  - kb
  - routes
  - analytics
aliases:
  - Analytics Route
kind: overview
status: active
updated: 2026-04-16
source_count: 4
---

# Analyst Route

Use this route when the question is basketball-first: leaders, trends, matchups, shooting, lineups, or season snapshots.

## Not this route when...
- the real issue is freshness, gaps, or failed refreshes
- the right next step is an operator rerun rather than a query

## Start in 30 seconds
| If you need... | Do this first |
| --- | --- |
| Query shape only | Start browser-first from docs or the SQL playground |
| Local warehouse rows | `uv run nbadb download` |
| Fresh current data | Switch immediately to [[operator-route|Operator Route]] |

> [!tip]
> Default read order: `analytics_*` -> `agg_*` -> `fact_*`.

## Good opening surfaces
| Need | Start here |
| --- | --- |
| Player game context | `analytics_player_game_complete` or `fact_player_game_log` |
| Team season summary | `analytics_team_season_summary` |
| Head-to-head | `analytics_head_to_head` |
| Clutch reads | `analytics_clutch_performance` |
| Season rollups | `agg_player_season`, `agg_team_season`, `agg_player_rolling` |
| Shot locations | `fact_shot_chart` or `fact_shot_chart_detail` |

## Guardrails
- Keep `season_year` and `season_type` explicit.
- `dim_player` and `dim_team_history` are SCD2; filter `is_current = TRUE` unless you want history.
- Count and join on IDs, not names.
- Verify whether the current environment exposes `fact_shot_chart` or `fact_shot_chart_detail`.

## Open next
- [[../topics/analytics-skill-guide|Analytics Skill Guide]]
- [[../topics/query-patterns|Query Patterns]]
- [[operator-route|Operator Route]] if the real problem is freshness, gaps, or failed refreshes.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| analyst route framing | `docs/content/docs/start/onboarding.mdx` | role-based onboarding |
| live-data startup path | `docs/content/docs/start/analytics-quickstart.mdx` | analytics workflow |
| SQL-first examples | `docs/content/docs/start/duckdb-queries.mdx` | query route |
| current analytics surfaces | `chat/skills/nba-data-analytics/references/schema-guide.md` | secondary schema-oriented reference |
