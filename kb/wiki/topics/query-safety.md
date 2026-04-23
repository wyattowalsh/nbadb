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
updated: 2026-04-14
source_count: 9
---

# Query Safety

Use this note for the shortest grounded answer to "where is read-only SQL actually enforced, and what parts of the agent stack are only guidance or trust assumptions?"

## Canonical enforcement point
The canonical SQL guard lives in `src/nbadb/agent/safety.py`.

`ReadOnlyGuard` does more than block obvious write verbs:
- normalizes SQL with Unicode NFKC before checking it
- strips block and line comments before validation
- rejects stacked statements after comment stripping
- rejects write keywords with word-boundary matching
- rejects dangerous file, environment, and external-read functions such as `read_csv`, `read_parquet`, `http_get`, `getenv`, and `query_table`
- only allows statements starting with `SELECT`, `WITH`, `EXPLAIN`, `SHOW`, or `DESCRIBE`

For executable reads, it also wraps `SELECT` and `WITH` queries in an outer hard `LIMIT`. `EXPLAIN`, `SHOW`, and `DESCRIBE` are allowed passthrough prefixes and are not limit-wrapped.

## Local query agent boundary
`src/nbadb/agent/query.py` is the narrowest trust boundary in the repo.

What it trusts:
- only fixed regex matches
- only canned SQL templates stored in `_PATTERNS`

What it does not trust:
- arbitrary model-generated SQL, because this surface does not generate SQL at all

Execution path:
1. match a question to a canned query
2. validate with `ReadOnlyGuard`
3. clamp and wrap with a hard limit
4. execute in DuckDB with `read_only=True`
5. disable external access
6. apply a statement timeout

If no pattern matches, the local agent stops at schema guidance and tells the user to write SQL directly. That fallback is a handoff, not autonomous SQL execution.

## Chat surface boundary
The chat app is broader and therefore relies on stronger runtime boundaries.

`chat/server/agent.py` injects the same system prompt into both backends, but the prompt is guidance, not enforcement.

`chat/server/prompts.py` tells the model that:
- `run_sql` is read-only and capped at 1000 rows
- SQL discovery should go through `list_tables` and `describe_table`
- Python should use `query(sql)` or `conn.execute(sql)` only
- raw `duckdb` module access is not available in the Python tool

That contract matters, but the real safety boundary is lower in the stack.

## Built-in chat query enforcement
The built-in chat SQL path reuses the same guard instead of defining a second policy.

- `chat/server/_safety.py` re-exports `ReadOnlyGuard` from `nbadb.agent.safety`
- `chat/server/_sql_exec.py` validates, wraps, and executes SQL for both MCP `run_sql` and the Copilot backend
- `chat/mcp_servers/sql.py` exposes `run_sql`, `list_tables`, and `describe_table` on top of that shared executor
- `chat/server/copilot_backend.py` wires its `run_sql` tool to the same shared executor

The built-in chat execution path therefore treats model-drafted SQL as untrusted until it passes through:
- `ReadOnlyGuard`
- DuckDB `read_only=True`
- `SET enable_external_access = false`
- a 30-second timeout when available

## Python tool boundary
The chat Python path is not a bypass for SQL safety.

`chat/server/_preamble.py` creates a private `_RAW_CONN` in `read_only=True` mode, disables external access, then exposes only:
- `conn.execute(...)`
- `conn.sql(...)`
- `query(sql)`

Those helpers route through `_prepare_sql(...)`, which reuses `ReadOnlyGuard` and applies a 1000-row cap before execution. The raw DuckDB module is deleted from the preamble after setup, so the prompt restriction is backed by code.

## Validator and trust assumptions
`chat/mcp_servers/sql_validator.py` is a preflight tool, not the primary enforcement point.

It:
- validates candidate SQL with `ReadOnlyGuard`
- asks DuckDB to parse `EXPLAIN` the query
- returns warnings about `SELECT *`, join duplication risk, and missing `LIMIT`

Treat it as advisory. Real enforcement still happens in the `run_sql` and safe Python execution paths.

The broadest explicit trust assumption in the chat stack is `extra_mcp_servers` in `chat/server/mcp_client.py`: those servers are treated as trusted because the config is user-owned. Built-in SQL safety does not automatically govern what an extra MCP server might do.

## Practical rule
Trust prompts for intent, but trust only execution wrappers for safety.

In this repo, the main read-only boundary is:
- canonical guard in `src/nbadb/agent/safety.py`
- reused by chat via `chat/server/_safety.py`
- enforced again at DuckDB connection time with read-only mode and external access disabled

## Related notes
- [[wiki/topics/query-agent|Query Agent]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-patterns|Query Patterns]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| canonical read-only guard behavior | `src/nbadb/agent/safety.py` | normalization, comment stripping, keyword and function blocks, limit wrapping |
| local query agent boundary and fallback | `src/nbadb/agent/query.py` | canned pattern matching, validation, execution settings |
| chat prompt contract | `chat/server/prompts.py` | tool instructions, 1000-row framing, Python SQL usage rules |
| backend-level prompt injection | `chat/server/agent.py` | same prompt passed into both Copilot and deepagents backends |
| chat reuse of canonical guard | `chat/server/_safety.py` | imports `ReadOnlyGuard` from `nbadb.agent.safety` |
| shared SQL execution policy | `chat/server/_sql_exec.py` | built-in `run_sql` enforcement path |
| MCP SQL tool surface | `chat/mcp_servers/sql.py` | read-only SQL tool on top of shared executor |
| chat Python safe connection path | `chat/server/_preamble.py` | guarded `conn` and `query(sql)` wrappers |
| validator role and trusted extension point | `chat/mcp_servers/sql_validator.py`; `chat/server/mcp_client.py` | advisory preflight vs trusted extra MCP servers |
