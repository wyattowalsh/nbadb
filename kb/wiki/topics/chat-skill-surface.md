---
title: Chat Skill Surface
tags:
  - kb
  - topics
  - chat
  - skills
  - agent
aliases:
  - Chat Skills
  - Deepagents Skill Surface
kind: concept
status: active
updated: 2026-04-22
source_count: 9
---

# Chat Skill Surface

This note covers the current `chat/skills/*` family behind the chat app.

## Runtime boundary
The deepagents path loads the `chat/skills/` directory as part of runtime assembly in `src/nbadb/chat/app/agent.py`.

The Copilot path does not load that directory directly. It mirrors the main capability families in-process instead.

So the skill surface is a first-class part of the deepagents runtime, not a generic repo-wide abstraction.

## Current shape
The current worktree has one broad umbrella skill plus eight narrower specialist skills:
- `nba-data-analytics`
- `nbadb-semantic-catalog`
- `warehouse-query-writing`
- `data-quality-debugging`
- `analysis-and-visualization`
- `artifact-creation`
- `follow-up-refinement`
- `connector-usage`
- `web-context-for-nba`

## Responsibility split
### Broad umbrella skill
`nba-data-analytics` still owns the helper-script package and the broad end-to-end NBA analysis playbook.

### Specialist skills
The newer skills split that broad contract into narrower responsibilities:
- semantic surface selection
- SQL drafting
- debugging suspicious outputs
- post-query analysis and visualization
- artifact persistence
- minimal-delta follow-up refinement
- runtime-capability adaptation
- live web-context augmentation

## Why the split matters
The split keeps responsibilities cleaner:
- warehouse planning is not mixed with charting
- debugging bad outputs is not mixed with raw SQL drafting
- persistence and replay are not mixed with analysis
- live web context stays explicitly separate from warehouse-backed facts

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/query-cookbook-families|Query Cookbook Families]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| deepagents skill-directory loading | `src/nbadb/chat/app/agent.py` | runtime assembly path |
| broad prompt-level workflow that the skills refine | `src/nbadb/chat/prompts.py` | prompt-to-skill relationship |
| current skill family | `chat/skills/nba-data-analytics/SKILL.md`; `chat/skills/nbadb-semantic-catalog/SKILL.md`; `chat/skills/warehouse-query-writing/SKILL.md`; `chat/skills/data-quality-debugging/SKILL.md`; `chat/skills/analysis-and-visualization/SKILL.md`; `chat/skills/artifact-creation/SKILL.md`; `chat/skills/follow-up-refinement/SKILL.md`; `chat/skills/connector-usage/SKILL.md`; `chat/skills/web-context-for-nba/SKILL.md` | current worktree skill roots |
| artifact and web-context alignment | `chat/mcp_servers/artifacts.py`; `src/nbadb/chat/app/agent.py` | specialist-skill runtime alignment |
| grouped skill evidence inventory | `kb/raw/extracts/internal/chat-skill-inventory.md` | current KB bridge |
