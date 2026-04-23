---
title: Table Family Guide
tags:
  - kb
  - model
  - schema
aliases:
  - Table Family Routing
kind: concept
status: active
updated: 2026-04-14
source_count: 5
---

# Table Family Guide

nbadb is an analytics-first warehouse. The safest way to navigate it is to read the table prefix first, then choose the narrowest surface that already matches your question.

## Public model at a glance
| Family | Prefix | Primary job |
| --- | --- | --- |
| Dimensions | `dim_` | Identity, history, calendar, lookup context |
| Facts | `fact_` | Measured events, summaries, and specialty analytical grains |
| Bridges | `bridge_` | Many-to-many connectors |
| Aggregates | `agg_` | Reusable pre-computed rollups |
| Analytics views | `analytics_` | Pre-joined convenience surfaces |

## Operational layers
| Layer | Prefix | Use it when... |
| --- | --- | --- |
| Raw | `raw_` | You need source-shaped payload context or are debugging extract fidelity |
| Staging | `stg_` | You need normalized upstream inputs, typed columns, or lineage checkpoints |
| Public model | `dim_`, `fact_`, `bridge_`, `agg_`, `analytics_` | You are writing queries, documenting the warehouse, or choosing a downstream model surface |

## Routing rules
1. Start with the smallest fact grain that already matches the final row you want.
2. Move up to `agg_` when the same summary would otherwise be rebuilt repeatedly.
3. Move up to `analytics_` when the win is fewer joins, not a different summary grain.
4. Drop to `stg_` or `raw_` only when tracing source quirks, validation issues, or `provenance`.
5. Use `bridge_` tables whenever the relationship is truly many-to-many.

## Watchouts
- `dim_player` and `dim_team_history` are SCD Type 2.
- `fact_box_score_*` and `fact_player_game_*` are not interchangeable.
- `raw_` and `stg_` are pipeline layers, not the reader-facing contract.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| analytics-first warehouse framing | `README.md` | public surface summary |
| naming conventions and family semantics | `AGENTS.md` | authoritative repo vocabulary |
| schema reading guidance | `docs/content/docs/start/reading-the-schema.mdx` | curated schema route |
| family navigation | `docs/content/docs/model/schema/index.mdx` | docs hub |
| secondary table examples | `chat/skills/nba-data-analytics/references/schema-guide.md` | example-oriented reference |
