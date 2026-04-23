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
updated: 2026-04-15
source_count: 12
---

# Chat Skill Surface

This note covers the skill layer behind `chat/`, especially the newer focused skills that now divide work that used to sit mostly inside `nba-data-analytics`.

## Runtime boundary
- The deepagents path loads every skill under `chat/skills/` by passing the skills directory into `create_deep_agent(...)`.
- The Copilot path exposes a parallel tool surface, but it does not load the skill directory directly.
- In practice, the skill surface is the planning and delegation layer for the deepagents backend, while Copilot relies more on the system prompt plus hard-coded tool registration.

## Current shape
- `nba-data-analytics` is still the broad tracked umbrella skill for SQL, Python, metrics, charts, and exports.
- Eight newer focused skills are present under `chat/skills/` and are currently untracked in git.
- Those newer skills split the chat workflow into narrower responsibilities so the agent can load the smallest useful instruction set for the current step.

## Responsibility split

| Skill | Primary job | When it should lead |
|-------|-------------|---------------------|
| `nbadb-semantic-catalog` | choose the right warehouse surface | entity/grain discovery before SQL |
| `warehouse-query-writing` | draft, validate, repair, and rerun SQL | the task is mainly warehouse retrieval |
| `data-quality-debugging` | debug wrong, empty, duplicated, or misleading results | SQL runs but output is not trustworthy |
| `analysis-and-visualization` | post-process, compare, visualize, and interpret | rows are correct and the task shifts to analysis |
| `artifact-creation` | save findings, templates, bundles, and replayable outputs | the work should persist beyond the reply |
| `follow-up-refinement` | modify the previous result with minimal changes | the user is iterating on an existing result |
| `web-context-for-nba` | add current external NBA context | warehouse truth is insufficient for current events |
| `connector-usage` | adapt behavior to connector and runtime capability differences | the access mode changes what tools are safe or available |
| `nba-data-analytics` | umbrella analytics playbook | broad end-to-end NBA analysis without a narrower fit |

## Recommended handoff order
1. `connector-usage` if runtime capabilities may constrain the plan.
2. `nbadb-semantic-catalog` to choose the right surface and grain.
3. `warehouse-query-writing` to retrieve the right rows.
4. `data-quality-debugging` only if validated SQL still produces suspect output.
5. `analysis-and-visualization` for metrics, tests, charts, and interpretation.
6. `artifact-creation` if the result should be saved or exported.
7. `follow-up-refinement` on later turns when the user wants a small delta from prior work.
8. `web-context-for-nba` when current external evidence must be layered on top of warehouse-backed facts.

## Why the split matters
- The semantic catalog skill owns table-family and grain selection, so SQL-writing guidance can stay narrower and more execution-oriented.
- The analysis skill assumes retrieval is already correct, which keeps Python use focused on post-processing instead of replacing SQL.
- The artifact skill separates persistence and replay concerns from analysis concerns.
- The follow-up skill protects session continuity by preserving prior grain, provenance, and intent.
- The web-context skill keeps external current-context evidence explicitly separate from warehouse-backed facts.
- The connector skill is cross-cutting and explains when the same plan must degrade gracefully across local, BYOK, login, Copilot, or sandbox differences.

## Tool and server alignment
- Semantic catalog work maps to `nbadb-catalog` tools such as `search_catalog`, `get_object`, and `recommend_surfaces`.
- Warehouse querying maps to `nbadb-sql` and `nbadb-sql-validator` tools such as `run_sql`, `describe_table`, `validate_sql`, `repair_sql`, and `estimate_query_risk`.
- Analysis and export work maps to the sandbox and Python lane.
- Artifact persistence maps to `nbadb-artifacts` when memory is enabled.
- Follow-up refinement depends on session artifacts, saved SQL, and memory-like state.
- Web context maps to local `web_search` and `web_fetch`, which are only added when `settings.web_context` is enabled.

## Practical reading
- Think of `nba-data-analytics` as the legacy umbrella contract.
- Think of the newer untracked skills as a decomposition of that contract into planning, retrieval, debugging, post-processing, persistence, iteration, runtime-awareness, and external-context slices.
- The split matches the prompt workflow closely: understand, choose surface, validate query, analyze, then present or save.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]
- [[wiki/topics/query-safety|Query Safety]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| deepagents loads the skills directory | `chat/server/agent.py` | `skills=[str(SKILLS_DIR)]` in `create_deep_agent(...)` |
| Copilot path uses direct tool registration instead of skill-directory loading | `chat/server/agent.py`; `chat/server/copilot_backend.py` | backend split |
| broad chat workflow and tool inventory | `src/nbadb/chat/prompts.py` | prompt-level operating contract |
| runtime capability and access-mode surface | `src/nbadb/chat/runtime/capabilities.py`; `src/nbadb/chat/runtime/factory.py` | capability manifest and prompt assembly |
| semantic-catalog role and handoff to SQL or analysis | `chat/skills/nbadb-semantic-catalog/SKILL.md` | surface selection skill |
| SQL drafting, validation, and repair responsibility | `chat/skills/warehouse-query-writing/SKILL.md`; `chat/mcp_servers/sql.py`; `chat/mcp_servers/sql_validator.py` | retrieval lane |
| result-debugging responsibility | `chat/skills/data-quality-debugging/SKILL.md` | post-query trust checks |
| post-processing, charting, and export interpretation | `chat/skills/analysis-and-visualization/SKILL.md` | analysis lane |
| artifact persistence and replay packaging | `chat/skills/artifact-creation/SKILL.md`; `chat/mcp_servers/artifacts.py` | durable artifact lane |
| follow-up refinement and minimal-delta iteration | `chat/skills/follow-up-refinement/SKILL.md` | multi-turn refinement lane |
| external current-context behavior | `chat/skills/web-context-for-nba/SKILL.md`; `chat/server/agent.py` | local web tools gated by `settings.web_context` |
| connector/runtime-aware behavior and current untracked status of the newer focused skills | `chat/skills/connector-usage/SKILL.md`; `git status --short -- chat/skills` | eight focused skill folders currently show as untracked |
