---
title: MCP Server Surface
tags:
  - kb
  - topics
  - chat
  - mcp
  - agent
aliases:
  - Chat MCP Surface
  - MCP Tool Bus
kind: concept
status: active
updated: 2026-04-15
source_count: 10
---

# MCP Server Surface

This note covers the built-in MCP server layer under `chat/mcp_servers/` and how that layer feeds the assembled chat agent's query, sandbox-analysis, and export/persistence flows.

## What this surface is
- The MCP server directory is the stdio tool surface for the deepagents chat backend.
- Each module wraps one capability area in a small FastMCP server with a stable server name.
- `chat/server/mcp_client.py` launches those servers as subprocesses and turns their tools into agent-callable tools.
- `chat/server/agent.py` then injects those tools into `create_deep_agent(...)` alongside optional web tools and chat skills.

That means the MCP layer is the concrete execution surface behind the assembled agent's main data workflow.

## Built-in servers
| Server | Module | Main tools | Primary role |
| --- | --- | --- | --- |
| `nbadb-sql` | `chat/mcp_servers/sql.py` | `run_sql`, `list_tables`, `describe_table` | read-only warehouse execution and inspection |
| `nbadb-catalog` | `chat/mcp_servers/catalog.py` | `search_catalog`, `get_object`, `recommend_surfaces` | semantic table discovery and planning |
| `nbadb-sql-validator` | `chat/mcp_servers/sql_validator.py` | `validate_sql`, `explain_sql`, `estimate_query_risk`, `repair_sql` | query preflight, guardrail feedback, lightweight repair help |
| `nbadb-sandbox` | `chat/mcp_servers/sandbox.py` | `run_python` | Python post-processing, charting, and export/share helpers |
| `nbadb-artifacts` | `chat/mcp_servers/artifacts.py` | `save_template`, `load_template`, `list_templates`, `save_finding`, `search_findings` | durable local artifact persistence |
| `nbadb-memory` | `chat/mcp_servers/memory.py` | `remember_preference`, `list_preferences`, `save_trajectory`, `search_trajectories`, `forget_memory` | local-first preference and trajectory memory |

## How it reaches the assembled agent
### Deepagents path
- `setup_mcp_tools(...)` starts the built-in servers over stdio.
- The always-on core is `sql`, `catalog`, `sql-validator`, and `sandbox`.
- `artifacts` and `memory` are added only when `memory_mode != "off"`.
- `create_nba_agent(...)` passes the resulting MCP tools into `create_deep_agent(...)`.

In practice, the assembled deepagents agent sees one flattened tool inventory, but those tools come from this MCP server bundle.

### Copilot contrast
- The Copilot backend does not talk to these MCP subprocesses.
- `chat/server/copilot_backend.py` mirrors most of the same tool semantics directly in-process.

So this note is about the canonical stdio tool bus for the deepagents runtime, not the only place where equivalent capabilities exist.

## Flow map
### 1. Query planning and execution flow
The query lane is intentionally split across three MCP servers:
- `nbadb-catalog` helps the agent find the right semantic surface before writing SQL.
- `nbadb-sql-validator` checks candidate SQL against `ReadOnlyGuard`, DuckDB parsing, and simple risk heuristics.
- `nbadb-sql` performs the actual read-only execution or schema inspection.

This separation matters because the agent is expected to plan, validate, and then execute, rather than jump straight from user text to unchecked SQL.

### 2. Sandbox analysis flow
- `nbadb-sandbox` owns the Python lane after retrieval is correct.
- `run_python` prepends the shared preamble from `chat/server/_preamble.py`.
- That preamble exposes a safe read-only DuckDB helper, `query(sql)`, plotting libraries, metric helpers, skill scripts, display helpers, and persisted `last_result` state.

This is the analysis lane for reshaping query results, computing derived metrics, and producing charts after the SQL step.

### 3. Export and persistence flow
There are two adjacent outcomes after analysis:
- transient exports from the sandbox
- durable saved artifacts and memory

The split is:
- `nbadb-sandbox` emits export payloads such as CSV, XLSX, JSON, spreadsheet HTML, embed HTML, social PNG, and thread text through helpers like `to_csv(...)`, `to_spreadsheet(...)`, `to_embed(...)`, and `to_social(...)`
- `nbadb-artifacts` persists reusable templates and findings under the local artifact store
- `nbadb-memory` persists preferences and successful analytical trajectories for later reuse

So export is mostly an immediate delivery lane, while artifacts and memory are the durable reuse lane.

## Session and trust boundaries
- `nbadb-sandbox` receives both the DuckDB path and a sanitized `session_id`; its `last_result` state lives under `~/.nbadb/session/<session_id>`.
- `nbadb-artifacts` and `nbadb-memory` also receive `session_id`, but they use it differently: artifacts embed it in saved finding metadata, while memory uses it when storing trajectories.
- `extra_mcp_servers` can be merged into the tool bundle from user config, and `mcp_client.py` treats those as trusted user-owned extensions.

## Practical mental model
- `catalog` decides where to look.
- `sql-validator` checks whether the candidate query is safe and sensible.
- `sql` fetches the warehouse result.
- `sandbox` turns results into analysis, charts, and outbound files.
- `artifacts` and `memory` preserve reusable outputs across sessions.

That is the MCP-backed execution backbone behind the assembled deepagents chat agent.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/export-share-artifacts|Export and Share Artifact Surfaces]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]
- [[wiki/topics/query-safety|Query Safety]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| built-in catalog server name and tool mapping | `chat/mcp_servers/catalog.py` | canonical semantic-discovery MCP surface |
| built-in SQL server name and tool mapping | `chat/mcp_servers/sql.py` | canonical read-only execution MCP surface |
| built-in SQL validation server name, validation flow, explain/risk/repair tools | `chat/mcp_servers/sql_validator.py` | canonical query-preflight MCP surface |
| built-in sandbox server name, `run_python` contract, session wiring | `chat/mcp_servers/sandbox.py` | canonical Python analysis MCP surface |
| artifact persistence server name and tool mapping | `chat/mcp_servers/artifacts.py` | canonical durable artifact MCP surface |
| memory server name and tool mapping | `chat/mcp_servers/memory.py` | canonical preference and trajectory MCP surface |
| stdio launch map, always-on vs gated servers, trusted `extra_mcp_servers` merge | `chat/server/mcp_client.py` | runtime assembly of the MCP bundle |
| assembled-agent handoff from MCP tools into `create_deep_agent(...)` | `chat/server/agent.py` | shows how the deepagents backend consumes the MCP surface |
| sandbox helper inventory, safe query helper, `last_result`, and export/share payload helpers | `chat/server/_preamble.py` | explains what `run_python` actually exposes |
| Copilot backend direct mirror of SQL, catalog, sandbox, artifact, and memory-like tools | `chat/server/copilot_backend.py` | contrast point: same capability family without MCP subprocesses |
