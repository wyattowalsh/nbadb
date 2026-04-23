---
title: Prompt Assembly And Capabilities
tags:
  - kb
  - topics
  - chat
  - runtime
  - prompts
  - capabilities
aliases:
  - Prompt Assembly
  - Capability Manifest Flow
kind: concept
status: active
updated: 2026-04-14
source_count: 7
---

# Prompt Assembly And Capabilities

This note covers how the chat runtime builds two session-level contracts before the agent backend is created:
- the system prompt string
- the `CapabilityManifest` attached to the assembled agent wrapper

The flow starts in `src/nbadb/chat/runtime/factory.py`, where prompt assembly and capability computation happen together, then ends in `chat/server/agent.py`, where both are handed into the selected backend and preserved on `NbaAgentWrapper`.

## End-to-end flow
1. `create_nba_agent(settings, profile=...)` calls `build_runtime_context(...)`.
2. `build_runtime_context(...)` resolves the database path, loads schema context, builds the system prompt, and computes the capability manifest.
3. `create_nba_agent(...)` branches to either `_create_copilot_agent(...)` or `_create_deepagents_agent(...)`.
4. Both backend constructors receive the same `system_prompt` and `CapabilityManifest`.
5. The backend-specific agent is wrapped in `NbaAgentWrapper`, which stores `capabilities` on the wrapper instance.

## Prompt assembly
`src/nbadb/chat/prompts.py` defines a single base system prompt template plus a small profile-specific suffix map.

### Base prompt contract
`_SYSTEM_PROMPT_TEMPLATE` hard-codes the main operating policy:
- role: expert NBA analyst with warehouse access
- workflow: understand request, prefer semantic surfaces, validate and repair SQL, use Python only after retrieval is correct, lead with insight
- tool inventory: SQL tools, catalog tools, Python, memory helpers, and web helpers
- database section: `{{schema_context}}` placeholder for live warehouse structure
- style rules: separate warehouse facts from external evidence, explain raw-table fallbacks, suggest next steps

### Profile augmentation
`build_system_prompt(schema_context, profile=None)` does only two things:
- replaces `{{schema_context}}` with the string returned from schema introspection
- appends a profile block if `profile` matches one of the known entries in `_PROFILE_INSTRUCTIONS`

Current supported profiles are:
- `Quick Stats`
- `Deep Analysis`
- `Visualization`

Important constraint: prompt customization is additive, not compositional. There is one canonical base prompt, and profiles only append extra instructions.

## Factory boundary
`src/nbadb/chat/runtime/factory.py` is the narrow assembly seam between settings and agent creation.

`build_runtime_context(settings, profile=...)` returns a three-part tuple:
- `db_path`
- `system_prompt`
- `capabilities`

Its job is intentionally small:
- `ensure_database(settings.duckdb_path)` guarantees a usable DuckDB file path
- `get_schema_context(db_path)` produces the schema text injected into the prompt
- `build_system_prompt(schema_context, profile=profile)` produces the final prompt string
- `build_capability_manifest(...)` derives runtime capability flags from normalized settings

This matters because backend selection happens after prompt and capability assembly. The Copilot and deepagents paths do not compute their own prompt variants or capability flags.

## Capability manifest flow
`src/nbadb/chat/runtime/capabilities.py` defines both the manifest schema and the policy for deriving it.

### Manifest shape
`CapabilityManifest` is a Pydantic model that captures what the runtime says the session can do, including:
- provider and access mode identity
- SQL and schema lookup availability
- semantic catalog, Python analysis, web search, artifact export, memory, and notebook support
- browser-use availability
- dual-SQL drafting and answer-judge toggles
- supported sandbox list

Most fields default to optimistic `True` values. The builder then adjusts the fields that are currently runtime-sensitive.

### Builder inputs
`build_capability_manifest(...)` takes four normalized settings inputs:
- `access_mode`
- `provider`
- `quality_mode`
- `sandbox_mode`

### Current derivation rules
- `browser_use` is enabled only for `AccessMode.COPILOT` and `AccessMode.OPENAI_LOGIN`
- `dual_sql_drafting` is enabled only when `quality_mode == CAREFUL`
- `answer_judge` is disabled only when `quality_mode == FAST`
- `supported_sandboxes` is always the full tuple `(LOCAL, DAYTONA, E2B)` in the current implementation

Notable nuance: `sandbox_mode` is passed in, but today it does not narrow the manifest output. The conditional expression returns the same full tuple in both branches.

## Agent handoff
`chat/server/agent.py` is where the assembled runtime context becomes a concrete agent instance.

### Shared assembly point
`create_nba_agent(...)` always starts with:

```python
db_path, system_prompt, capabilities = build_runtime_context(settings, profile=profile)
```

That line is the central handoff from shared runtime assembly into backend-specific construction.

### Copilot path
The Copilot branch passes `system_prompt` and `db_path` into `server.copilot_backend.create_copilot_agent(...)`, then wraps the result with:

```python
NbaAgentWrapper(agent, capabilities=capabilities)
```

### Deepagents path
The deepagents branch:
- creates the model
- sets up MCP tools
- optionally adds local `web_search` and `web_fetch`
- configures `LocalShellBackend(root_dir=db_path.parent)`
- passes `system_prompt` into `create_deep_agent(...)`
- returns `NbaAgentWrapper(agent, mcp_client, capabilities=capabilities)`

The important split is:
- `system_prompt` is consumed by the backend agent constructor
- `capabilities` is not passed into `create_deep_agent(...)`; it is preserved on the wrapper as metadata about the assembled session

## Design implications
- Prompt assembly is centralized. There is no backend-specific prompt fork in `agent.py`.
- Capability computation is also centralized. Backend constructors consume the result; they do not redefine it.
- The wrapper is the stable place to inspect session capabilities after assembly, regardless of backend.
- Schema context is injected before backend creation, so both agent runtimes see the same warehouse description.
- Profile selection only affects prompt text, not capability flags.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| base prompt template, profile map, and `build_system_prompt(...)` behavior | `src/nbadb/chat/prompts.py` | canonical prompt assembly logic |
| runtime tuple assembly in `build_runtime_context(...)` | `src/nbadb/chat/runtime/factory.py` | canonical prompt-plus-capabilities seam |
| capability enums, manifest schema, and derivation rules | `src/nbadb/chat/runtime/capabilities.py` | canonical capability policy |
| backend branching, wrapper storage, and handoff of prompt/capabilities | `chat/server/agent.py` | canonical runtime assembly consumer |
| settings normalization that feeds capability derivation | `src/nbadb/chat/runtime/settings.py` | `quality_mode`, `access_mode`, and `sandbox_mode` normalization |
| schema-context injection source | `src/nbadb/chat/db.py` | `ensure_database(...)` and `get_schema_context(...)` feed factory assembly |
| runtime package export surface | `src/nbadb/chat/runtime/__init__.py` | confirms `build_runtime_context` and capability APIs are public runtime entry points |
