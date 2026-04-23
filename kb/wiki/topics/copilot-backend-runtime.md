---
title: Copilot Backend Runtime
tags:
  - kb
  - topics
  - chat
  - copilot
  - runtime
  - agent
aliases:
  - Copilot Runtime Path
  - Alternate Chat Runtime
kind: concept
status: active
updated: 2026-04-15
source_count: 8
---

# Copilot Backend Runtime

This note covers `chat/server/copilot_backend.py` as the alternate chat runtime used when `provider == "copilot"`.

## What it is
- `chat/server/agent.py` branches to this backend only for the Copilot provider.
- In this path, the app does not create a deepagents agent and does not launch MCP subprocess servers.
- Instead, it starts a `CopilotClient`, registers NBA tools directly with `@define_tool`, and wraps the resulting Copilot session behind the same `astream()` shape used elsewhere in the chat app.

The practical meaning is: Copilot owns the agent loop and context management, while nbadb still owns the NBA-specific tools and rendering adapter.

## Tool mirror

| Copilot tool | Closest MCP or deepagents analogue | Notes |
| --- | --- | --- |
| `run_sql` | `nbadb-sql.run_sql` | same shared `execute_safe_sql(...)` + `ReadOnlyGuard` path |
| `list_tables` | `nbadb-sql.list_tables` | same table-listing helper |
| `describe_table` | `nbadb-sql.describe_table` | same schema-inspection helper |
| `run_python` | `nbadb-sandbox.run_python` | same safety check, same preamble family, same raw-payload passthrough |
| `search_catalog_tool` | `nbadb-catalog.search_catalog` | same semantic warehouse discovery family |
| `get_object` | `nbadb-catalog.get_object` | same exact-object metadata lookup |
| `recommend_surfaces_tool` | `nbadb-catalog.recommend_surfaces` | same entity-and-grain surface recommendation |
| `validate_sql` | `nbadb-sql-validator.validate_sql` | directly calls the validator module's internal `_validate(...)` |
| `repair_sql` | `nbadb-sql-validator.repair_sql` | diverges: Copilot returns fixed generic suggestions, not the full repair service |
| `save_template`, `load_template`, `save_finding` | `nbadb-artifacts.*` | direct `ArtifactStore()` mirror |
| `remember_preference`, `search_trajectories` | `nbadb-memory.*` | partial `MemoryStore()` mirror |

## Important gaps versus the MCP path
The Copilot runtime mirrors most of the core capability families, but not the full MCP surface.

Missing on the Copilot path:
- SQL validator extras: `explain_sql`, `estimate_query_risk`
- artifact extras: `list_templates`, `search_findings`
- memory extras: `list_preferences`, `save_trajectory`, `forget_memory`
- deepagents-only wiring: skill-directory loading from `chat/skills/`
- deepagents-only local tools: `web_search` and `web_fetch` gated by `settings.web_context`

So Copilot is a narrower in-process mirror, not a byte-for-byte replacement for the MCP plus deepagents stack.

## Session behavior
- `create_copilot_agent(...)` starts one `CopilotClient`, builds tools once, and returns a `CopilotAgentWrapper`.
- The wrapper lazily creates the Copilot session on the first `astream(...)` call, not at construction time.
- That session is then cached in `self._session` and reused across later turns until `cleanup()` runs.
- Session creation uses an allowlist-based permission handler, so only the explicitly registered nbadb tools are approved.
- The system prompt is attached through `system_prompt_append=self._system_prompt` when the Copilot session is created.

Session-scoped side effects still matter even though there is no MCP client:
- `run_python` builds a sanitized session directory under `~/.nbadb/session/<session_id>` for sandbox state such as `last_result`.
- `save_finding` injects the current `session_id` into saved metadata.

## Streaming and event mapping
`CopilotAgentWrapper.astream(...)` is the adapter that makes Copilot events look like the messages expected by the rest of the chat stack.

Event mapping:
- last user message content becomes the prompt sent to `session.send(...)`
- Copilot `message_delta` events become incremental `AIMessage(content=delta)` chunks
- Copilot tool-result events become `ToolMessage(...)` values, with tool output normalized to string or JSON text and tool arguments exposed in metadata as `{"input": ...}`
- non-delta final message events are ignored because the deltas have already been streamed
- `idle` ends the stream
- `error` becomes an `AIMessage` formatted as `**Error:** ...`
- a 120-second wait timeout also yields a user-visible timeout error message

This is the key compatibility seam: Chainlit and the higher-level wrapper can consume Copilot and deepagents through the same `astream()` contract even though the underlying runtime events differ.

## Divergence from the MCP and deepagents path

| Area | Copilot runtime | MCP or deepagents runtime |
| --- | --- | --- |
| backend loop | Copilot SDK session | `create_deep_agent(...)` |
| tool transport | direct in-process Python callables | stdio MCP subprocess servers via `MultiServerMCPClient` |
| skill loading | none | loads `chat/skills/` |
| web tools | none in this module | optional `web_search` and `web_fetch` when `web_context` is enabled |
| sandbox execution | direct call from tool handler | MCP `nbadb-sandbox` server |
| artifacts and memory | direct store instances | dedicated artifact and memory MCP servers |
| session lifetime | one cached Copilot session per wrapper | MCP client treated as effectively stateless; deepagents owns turn flow |

The safest mental model is:
- deepagents path = skill-driven agent plus MCP tool bus
- Copilot path = Copilot-native runtime plus a hard-coded tool mirror

## Related notes
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/chat-skill-surface|Chat Skill Surface]]
- [[wiki/topics/query-safety|Query Safety]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| provider-based branch into Copilot vs deepagents | `chat/server/agent.py` | canonical backend split |
| Copilot backend role, client startup, direct tool registration, and wrapper construction | `chat/server/copilot_backend.py` | canonical alternate runtime implementation |
| deepagents assembly with MCP tools, skills, and optional web tools | `chat/server/agent.py`; `chat/server/mcp_client.py` | contrast path for divergence claims |
| SQL mirror behavior and shared read-only execution helpers | `chat/server/copilot_backend.py`; `chat/mcp_servers/sql.py` | confirms same capability family and helper reuse |
| validator differences, including missing `explain_sql` and `estimate_query_risk` on the Copilot path | `chat/server/copilot_backend.py`; `chat/mcp_servers/sql_validator.py` | Copilot mirrors only validation and a simplified repair flow |
| sandbox session directory, code safety, and raw result passthrough | `chat/server/copilot_backend.py`; `chat/mcp_servers/sandbox.py` | confirms same sandbox family with in-process wiring |
| artifact and memory mirror versus fuller MCP surface | `chat/server/copilot_backend.py`; `chat/mcp_servers/artifacts.py`; `chat/mcp_servers/memory.py` | shows which persistence tools are mirrored and which are absent |
| `astream()` event adaptation into `AIMessage` and `ToolMessage` plus timeout or error behavior | `chat/server/copilot_backend.py`; `chat/server/agent.py` | compatibility layer that lets higher-level chat code treat both backends similarly |
