---
title: Chat Surface
tags:
  - kb
  - topics
  - chat
  - agent
aliases:
  - Chat App Surface
kind: concept
status: active
updated: 2026-04-14
source_count: 6
---

# Chat Surface

This note covers the richer analytical assistant under `chat/`. It is the full agent surface: multi-tool, profile-aware, schema-injected, and designed for iterative analysis rather than canned query matching.

## Runtime shape
`create_nba_agent()` builds the chat agent in three steps:
1. ensure the database path exists and fetch schema context
2. build the system prompt, optionally with a profile
3. choose a backend: `copilot` or `deepagents`

Both backends are wrapped in `NbaAgentWrapper`, which standardizes streaming and exposes `cleanup()` so MCP-backed resources do not leak across sessions.

## Backend split
### Copilot path
The Copilot path delegates to `server.copilot_backend.create_copilot_agent(...)`.

### Deepagents path
The deepagents path:
- creates the chat model
- sets up MCP tools
- adds local `web_search` and `web_fetch`
- loads skills from `chat/skills`
- uses `LocalShellBackend(root_dir=db_path.parent)`
- passes the schema-injected system prompt into `create_deep_agent(...)`

## Prompt contract
The system prompt frames the workflow as:
1. Understand
2. Query
3. Analyze
4. Present

Important expectations:
- prefer `analytics_*` views first
- fall back to `fact_*` and `dim_*` when needed
- ask a brief clarifying question if the request is ambiguous
- lead with the insight, not the raw data

## Profiles
The chat prompt currently supports three appended profile modes:
- `Quick Stats`
- `Deep Analysis`
- `Visualization`

## Skill contract
The `nba-data-analytics` skill is narrower than the full prompt surface and codifies metric helpers, table-selection heuristics, SCD2 gotchas, charting helpers, and export helpers.

## Relationship to the local query agent
The chat surface is materially richer than [[wiki/topics/query-agent|Query Agent]].

The local query agent is regex-based, canned-SQL, and intentionally narrow.

The chat surface is backend-selectable, tool-augmented, schema-injected, iterative, analysis-first, and capable of Python post-processing and charts.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| backend selection and wrapper | `chat/server/agent.py` | runtime assembly |
| prompt workflow and tool contract | `chat/server/prompts.py` | system prompt contract |
| profile support | `chat/server/prompts.py` | appended profile modes |
| skill layer | `chat/skills/nba-data-analytics/SKILL.md` | domain-specific analysis rules |
| public contrast point | `README.md` | `ask` surface framing |
| docs-side route context | `wiki/topics/analytics-skill-guide.md` | current skill note |
