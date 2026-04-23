---
title: Query Safety
tags:
  - kb
  - topics
  - agent
  - sql
  - safety
  - trust-boundary
aliases:
  - Read-Only SQL Safety
  - Query Trust Boundaries
kind: concept
status: active
updated: 2026-04-22
source_count: 9
---

# Query Safety

Use this note for the shortest grounded answer to "where is read-only SQL actually enforced, and what parts of the chat stack are only guidance?"

## Canonical enforcement point
The repo-wide read-only SQL guard still lives in `src/nbadb/agent/safety.py`.

That guard:
- normalizes SQL before checking it
- strips comments before validation
- blocks write-oriented statements and dangerous file/network helpers
- only allows read-style entry prefixes
- wraps executable reads in a hard outer `LIMIT`

## Local query agent boundary
`src/nbadb/agent/query.py` is the narrowest trust boundary in the repo:
- fixed regex matches
- canned SQL only
- no model-generated SQL

If it cannot match a canned pattern, it stops instead of improvising.

## Chat runtime boundary
The chat app is broader, but the real safety boundary is still below the prompt.

Prompt and tool descriptions in `src/nbadb/chat/prompts.py` are guidance. Enforcement happens in shared runtime code:
- `src/nbadb/chat/sql/safety.py`
- `src/nbadb/chat/sql/exec.py`
- `src/nbadb/chat/app/preamble.py`
- `src/nbadb/chat/mcp/sql.py`
- `src/nbadb/chat/mcp/sql_validator.py`

## Built-in SQL execution path
The built-in chat SQL path reuses the shared read-only contract.

### Direct SQL tools
`src/nbadb/chat/sql/exec.py` is the shared execution lane used by the chat runtime. It validates with the read-only guard, opens DuckDB in read-only mode, disables external access, and returns structured result payloads.

### MCP path
`src/nbadb/chat/mcp/sql.py` and the app-local entrypoint `chat/mcp_servers/sql.py` expose the read-only SQL tool surface for the deepagents runtime.

### Copilot path
`src/nbadb/chat/app/copilot_backend.py` mirrors the same family in-process rather than bypassing it.

## Python analysis path
`run_python` is not a bypass for SQL safety.

`src/nbadb/chat/app/preamble.py` builds the Python helper environment and exposes only guarded SQL entrypoints such as:
- `conn.execute(sql)`
- `conn.sql(sql)`
- `query(sql)`

Those helpers still route through the shared read-only SQL policy before DuckDB sees the statement.

## Validator role
The validator surface is advisory, not the final enforcement point.

`src/nbadb/chat/sql/service.py` and `src/nbadb/chat/mcp/sql_validator.py`:
- preflight SQL with the guard
- ask DuckDB to parse or explain it
- surface warnings about joins, grain, and query risk

That is useful for planning and repair, but the final safety boundary is still the execution layer and the read-only DuckDB connection.

## Important trust distinction
Trust prompts for workflow, but trust executors for safety.

In the current v1 chat stack:
- prompts say what the model should do
- validators say whether a candidate query looks acceptable
- executors are what actually enforce read-only behavior

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/sandbox-runtime-contract|Sandbox Runtime Contract]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| canonical repo-wide read-only guard | `src/nbadb/agent/safety.py` | normalization, filtering, and limit wrapping |
| narrow local query-agent boundary | `src/nbadb/agent/query.py` | canned-query trust boundary |
| prompt-level workflow guidance | `src/nbadb/chat/prompts.py` | guidance layer, not enforcement |
| shared chat SQL safety and execution | `src/nbadb/chat/sql/safety.py`; `src/nbadb/chat/sql/exec.py`; `src/nbadb/chat/sql/service.py` | shared runtime enforcement and validator layer |
| Python helper environment and guarded SQL entrypoints | `src/nbadb/chat/app/preamble.py` | safe analysis namespace |
| MCP SQL and validator surfaces | `src/nbadb/chat/mcp/sql.py`; `src/nbadb/chat/mcp/sql_validator.py`; `chat/mcp_servers/sql.py`; `chat/mcp_servers/sql_validator.py` | deepagents tool path |
| Copilot in-process mirror | `src/nbadb/chat/app/copilot_backend.py` | alternate backend still using the same capability family |
| backend assembly path | `src/nbadb/chat/app/agent.py` | runtime branch point |
| broader sandbox and renderer context | `kb/wiki/topics/sandbox-runtime-contract.md`; `kb/wiki/topics/chainlit-runtime.md` | companion notes |
