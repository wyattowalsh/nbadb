---
title: Analytics Skill Guide
tags:
  - kb
  - topics
  - analytics
  - skills
aliases:
  - NBA Data Analytics Skill
kind: entity
status: active
updated: 2026-04-14
source_count: 3
---

# Analytics Skill Guide

Use `nba-data-analytics` when the ask needs more than a simple table read.

## Reach for it when
- the question needs multi-table star-schema joins
- you need TS%, eFG%, usage rate, or rating formulas
- you want shot charts, trend charts, or Plotly output
- you are doing lineup, on/off, similarity, or rolling-window work

## Default playbook
1. `list_tables` to confirm the surface
2. `describe_table` before guessing columns
3. `run_sql` for the base pull
4. `run_python` for derived metrics, charts, and exports

> [!tip]
> Prefer `analytics_*` first. They save join work and make the first answer faster.

## Open next
- [[query-patterns|Query Patterns]]
- [[../routes/analyst-route|Analyst Route]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| skill identity and allowed tools | `chat/skills/nba-data-analytics/SKILL.md` | concrete skill contract |
| table-selection guidance | `chat/skills/nba-data-analytics/references/schema-guide.md` | example-oriented routing |
| query pattern menu | `chat/skills/nba-data-analytics/references/query-cookbook.md` | reusable SQL shapes |
