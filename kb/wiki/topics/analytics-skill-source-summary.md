---
title: Analytics Skill Source Summary
tags:
  - kb
  - source
  - skills
aliases: []
kind: source-summary
status: active
updated: 2026-04-22
source_count: 7
---

# Analytics Skill Source Summary

## Source record
| Field | Value |
|-------|-------|
| Source ID | `analytics-skill` |
| Raw source | `chat/skills/nba-data-analytics/SKILL.md`; `chat/skills/*.md`; `src/nbadb/chat/app/agent.py`; `src/nbadb/chat/prompts.py`; `chat/skills/nba-data-analytics/references/` |
| Capture or extract | `raw/extracts/internal/chat-surface-manifest.md`; `raw/extracts/internal/chat-skill-inventory.md`; `raw/extracts/internal/analytics-helper-surface-manifest.md` |
| Status | captured |

## Summary
This source set documents the current worktree chat skill family. `nba-data-analytics` still carries the broad helper-script surface, but the chat runtime now also uses narrower specialist skills for semantic planning, SQL drafting, debugging, visualization, artifact packaging, refinement, connector differences, and live web context.

## Planned wiki coverage
- `wiki/topics/analytics-skill-guide.md`
- `wiki/topics/query-patterns.md`
- `wiki/topics/chat-surface.md`
- `wiki/topics/chat-skill-surface.md`
- `wiki/topics/query-cookbook-families.md`

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Skill identity and allowed tools | `chat/skills/nba-data-analytics/SKILL.md` | Concrete skill contract |
| Narrow specialist-skill boundaries | `chat/skills/nbadb-semantic-catalog/SKILL.md`; `chat/skills/warehouse-query-writing/SKILL.md`; `chat/skills/data-quality-debugging/SKILL.md`; `chat/skills/analysis-and-visualization/SKILL.md`; `chat/skills/artifact-creation/SKILL.md`; `chat/skills/follow-up-refinement/SKILL.md`; `chat/skills/connector-usage/SKILL.md`; `chat/skills/web-context-for-nba/SKILL.md` | Current v1 skill family |
| Analytics-first table selection and helper surface | `chat/skills/nba-data-analytics/SKILL.md`; `chat/skills/nba-data-analytics/references/query-cookbook.md`; `chat/skills/nba-data-analytics/references/schema-guide.md` | Preferred table routing plus helper guidance |
| Runtime wiring | `src/nbadb/chat/app/agent.py` | Skill loading in chat runtime |
| Prompt-level operating rules | `src/nbadb/chat/prompts.py` | Analytics-first workflow hints |
| Current grouped evidence inventory | `raw/extracts/internal/chat-surface-manifest.md`; `raw/extracts/internal/chat-skill-inventory.md`; `raw/extracts/internal/analytics-helper-surface-manifest.md` | Current worktree bridge layer |
