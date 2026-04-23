---
title: Analytics Skill Source Summary
tags:
  - kb
  - source
  - skills
aliases: []
kind: source-summary
status: active
updated: 2026-04-14
source_count: 5
---

# Analytics Skill Source Summary

## Source record
| Field | Value |
|-------|-------|
| Source ID | `analytics-skill` |
| Raw source | `chat/skills/nba-data-analytics/SKILL.md`; `chat/server/agent.py`; `chat/server/prompts.py`; `chat/skills/nba-data-analytics/references/schema-guide.md`; `chat/skills/nba-data-analytics/references/query-cookbook.md` |
| Capture or extract | future `raw/extracts/internal/chat-surface-manifest.md` |
| Status | seeded |

## Summary
This source set documents a real chat-side skill, `nba-data-analytics`, rather than a hypothetical KB skill. The skill is wired into the chat runtime, grants SQL/schema/Python tool access, prefers `analytics_*` views, and ships helper references for metrics, charts, comparisons, similarity, lineups, and trends.

## Planned wiki coverage
- `wiki/topics/analytics-skill-guide.md`
- `wiki/topics/query-patterns.md`
- future `wiki/topics/chat-surface.md`

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Skill identity and allowed tools | `chat/skills/nba-data-analytics/SKILL.md` | Concrete skill contract |
| Analytics-first table selection and SCD2 guidance | `chat/skills/nba-data-analytics/SKILL.md` | Preferred table routing |
| Helper APIs and cookbook pattern | `chat/skills/nba-data-analytics/SKILL.md` | Metrics, chart, and export helpers |
| Runtime wiring | `chat/server/agent.py` | Skill loading in chat runtime |
| Prompt-level operating rules | `chat/server/prompts.py` | Analytics-first workflow hints |
