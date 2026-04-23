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
updated: 2026-04-22
source_count: 8
---

# MCP Server Surface

This note covers the current MCP layout for the chat app.

## Split
There are two layers:
- `chat/mcp_servers/*` is the app-local stdio entrypoint layer
- `src/nbadb/chat/mcp/*` is the shared implementation layer

The app shell needs the `chat/mcp_servers/*` entrypoints because those are what the stdio launcher invokes, but the reusable logic lives in `src/nbadb/chat/mcp/*`.

## Built-in server families
The built-in families are:
- SQL
- semantic catalog
- SQL validator
- sandbox
- artifacts
- memory

Each family has:
- one app-local entrypoint in `chat/mcp_servers/*`
- one shared implementation in `src/nbadb/chat/mcp/*`

## Runtime wiring
`src/nbadb/chat/app/mcp_client.py` is the canonical launcher for the deepagents path.

It:
- starts the built-in servers over stdio
- always includes SQL, catalog, validator, and sandbox
- conditionally includes artifacts and memory when persistent memory is enabled
- optionally merges trusted `extra_mcp_servers`

`src/nbadb/chat/app/agent.py` then consumes the resulting tool surface when the selected backend is not Copilot.

## Relationship to Copilot
The Copilot path does not use the stdio MCP client.

Instead, `src/nbadb/chat/app/copilot_backend.py` mirrors the same main capability families in-process. That means MCP is the canonical transport for the deepagents path, not the only place those capabilities exist.

## Practical mental model
- app-local `chat/mcp_servers/*` = launchable server entrypoints
- shared `src/nbadb/chat/mcp/*` = reusable server logic
- `src/nbadb/chat/app/mcp_client.py` = tool-bus assembly
- `src/nbadb/chat/app/agent.py` = backend switchboard that either uses that MCP bus or the Copilot mirror

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/copilot-backend-runtime|Copilot Backend Runtime]]
- [[wiki/topics/sandbox-runtime-contract|Sandbox Runtime Contract]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| app-local MCP entrypoints | `chat/mcp_servers/sql.py`; `chat/mcp_servers/catalog.py`; `chat/mcp_servers/sql_validator.py`; `chat/mcp_servers/sandbox.py`; `chat/mcp_servers/artifacts.py`; `chat/mcp_servers/memory.py` | stdio entrypoint layer |
| shared MCP implementations | `src/nbadb/chat/mcp/sql.py`; `src/nbadb/chat/mcp/catalog.py`; `src/nbadb/chat/mcp/sql_validator.py`; `src/nbadb/chat/mcp/sandbox.py`; `src/nbadb/chat/mcp/artifacts.py`; `src/nbadb/chat/mcp/memory.py` | reusable implementation layer |
| MCP launcher and gated built-in bundle | `src/nbadb/chat/app/mcp_client.py` | canonical tool-bus assembly |
| backend switchboard that consumes MCP on the deepagents path | `src/nbadb/chat/app/agent.py` | runtime branch point |
| in-process mirror on the Copilot path | `src/nbadb/chat/app/copilot_backend.py` | non-MCP contrast |
| backing artifact and memory stores | `src/nbadb/chat/artifacts/store.py`; `src/nbadb/chat/memory/store.py` | durable persistence surfaces |
| grouped KB evidence layer | `kb/raw/extracts/internal/mcp-server-inventory.md` | maintained extract bridge |
| UI/runtime consumer of the resulting tool surface | `chat/chainlit_app.py` | higher-level app consumer |
