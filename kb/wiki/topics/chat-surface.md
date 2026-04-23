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
updated: 2026-04-22
source_count: 8
---

# Chat Surface

This note covers the current v1 chat surface in the worktree. The chat system is now split deliberately between shared runtime code in `src/nbadb/chat/*` and the app shell in `chat/`.

## Topology
### Shared runtime
The canonical shared logic lives in `src/nbadb/chat/*`:
- `runtime/*` builds the database, schema context, system prompt, and capability manifest
- `app/agent.py` assembles the actual runtime and chooses the backend
- `app/copilot_backend.py` is the in-process Copilot path
- `app/mcp_client.py` wires the deepagents MCP tool bus
- `catalog/*`, `sql/*`, `memory/*`, `artifacts/*`, `sandbox/*`, and `web/*` hold the reusable capability implementations

### App shell
The app-facing shell lives in `chat/`:
- `chat/chainlit_app.py` is the UI/session/rendering surface
- `chat/chainlit.md` is the user-facing app framing
- `chat/mcp_servers/*` is the stdio entrypoint layer for MCP servers
- `chat/skills/*` is the skill family used by the deepagents runtime

`chat/server/*` still exists, but it should be read as compatibility wrapper surface unless the note is explicitly about one of those shims.

## Backend split
`src/nbadb/chat/app/agent.py` always starts from the same shared runtime context:
1. resolve the DuckDB path
2. load schema context
3. build the system prompt
4. derive the capability manifest
5. branch to either Copilot or deepagents

### Copilot path
- uses `src/nbadb/chat/app/copilot_backend.py`
- mirrors the main NBA tool families in-process
- does not load the `chat/skills/` directory directly
- does not use the stdio MCP client

### Deepagents path
- uses `src/nbadb/chat/app/mcp_client.py`
- launches the built-in MCP server bundle
- loads the `chat/skills/` directory
- attaches local web tools only when `settings.web_context` is enabled

## Skill and helper shape
The skill surface is now broader than one umbrella skill.

`chat/skills/nba-data-analytics/` still carries the broad analytics helper package, but the current worktree also has narrower specialist skills for:
- semantic planning
- SQL drafting
- debugging bad results
- analysis and visualization
- artifact creation
- follow-up refinement
- connector/runtime differences
- live NBA web context

## Relationship to the local query agent
[[wiki/topics/query-agent|Query Agent]] is still the narrow regex-and-template surface under `src/nbadb/agent/*`.

The chat surface is the richer assistant stack:
- schema-injected
- backend-selectable
- tool-augmented
- skill-routed
- able to move from retrieval into Python analysis and durable artifacts

## Related notes
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/chat-skill-surface|Chat Skill Surface]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| shared runtime topology and backend assembly | `src/nbadb/chat/app/agent.py`; `src/nbadb/chat/runtime/factory.py` | canonical runtime split |
| Copilot runtime path | `src/nbadb/chat/app/copilot_backend.py` | in-process alternate backend |
| MCP-backed deepagents runtime path | `src/nbadb/chat/app/mcp_client.py` | stdio MCP assembly |
| prompt and capability surfaces | `src/nbadb/chat/prompts.py`; `src/nbadb/chat/runtime/capabilities.py` | prompt and capability contract |
| app shell and UI runtime | `chat/chainlit_app.py`; `chat/chainlit.md` | app-local Chainlit surface |
| app-local MCP entrypoint layer | `chat/mcp_servers/` | stdio entrypoints for the app shell |
| current skill family | `chat/skills/` | current worktree skill roots |
| grouped current-worktree evidence layer | `kb/raw/extracts/internal/chat-surface-manifest.md`; `kb/raw/extracts/internal/chat-skill-inventory.md` | current KB bridge |
