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
updated: 2026-04-22
source_count: 7
---

# Copilot Backend Runtime

This note covers `src/nbadb/chat/app/copilot_backend.py`, the alternate chat runtime used when `provider == "copilot"`.

## Role
The Copilot path is the in-process backend.

It:
- starts a Copilot client
- registers NBA tools directly in-process
- adapts Copilot event flow into the same `astream()` shape the UI expects
- reuses the shared runtime context built before backend selection

It does not use the stdio MCP client or load the `chat/skills/` directory directly.

## Relationship to the main assembly flow
`src/nbadb/chat/app/agent.py` is still the branch point.

The flow is:
1. build shared runtime context in `src/nbadb/chat/runtime/factory.py`
2. if provider is `copilot`, delegate to `src/nbadb/chat/app/copilot_backend.py`
3. otherwise use the deepagents + MCP path

So Copilot is an alternate backend under one shared top-level runtime contract, not a separate app architecture.

## Tool mirror
The Copilot backend mirrors the main capability families directly:
- SQL execution and inspection
- semantic catalog search
- SQL validation and simplified repair
- sandboxed Python analysis
- artifact persistence
- memory retrieval/persistence

The mirror is intentionally narrower than the richest MCP surface. The Copilot path still omits some MCP-only helper operations such as the full explain/risk validator surface and some artifact or memory listing tools.

## Important divergence
### Copilot path
- tool registration is direct and in-process
- there is no skill-directory loading
- local web tools are not attached on this path

### Deepagents path
- tools come from the MCP bundle built by `src/nbadb/chat/app/mcp_client.py`
- `chat/skills/*` participates in planning/delegation
- local web tools can be attached when enabled

## Compatibility point
The important compatibility seam is streaming:
- Copilot backend events are adapted into `AIMessage` and `ToolMessage`
- higher-level chat code consumes the same wrapper shape regardless of backend

That compatibility is why the UI can stay backend-agnostic while the runtime underneath differs materially.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/query-safety|Query Safety]]
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| provider-based branch into Copilot vs deepagents | `src/nbadb/chat/app/agent.py` | canonical backend split |
| Copilot backend role, tool mirror, and stream adapter | `src/nbadb/chat/app/copilot_backend.py` | canonical alternate runtime implementation |
| shared prompt/capability assembly before backend selection | `src/nbadb/chat/runtime/factory.py`; `src/nbadb/chat/prompts.py`; `src/nbadb/chat/runtime/capabilities.py` | shared pre-backend context |
| contrast against MCP-backed deepagents assembly | `src/nbadb/chat/app/mcp_client.py`; `chat/mcp_servers/` | alternate tool transport |
| shared SQL, catalog, sandbox, artifact, and memory families | `src/nbadb/chat/sql/`; `src/nbadb/chat/catalog/`; `src/nbadb/chat/sandbox/`; `src/nbadb/chat/artifacts/`; `src/nbadb/chat/memory/` | underlying shared capability implementations |
| app-local MCP entrypoint layer for the non-Copilot path | `chat/mcp_servers/` | deepagents-only stdio surface |
| runtime rendering compatibility expectations | `chat/chainlit_app.py` | higher-level consumer of the unified stream shape |
