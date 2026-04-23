---
title: Chainlit Runtime
tags:
  - kb
  - topics
  - chat
  - chainlit
  - runtime
aliases:
  - Chat Chainlit Runtime
  - Chainlit App Runtime
kind: concept
status: active
updated: 2026-04-22
source_count: 8
---

# Chainlit Runtime

This note covers the current `chat/chainlit_app.py` runtime surface: the UI shell, session lifecycle, message/step rendering, and export interactions for the chat app.

## Boundary
The Chainlit layer is not the analytical core.

It owns:
- session setup and teardown
- profile and settings UI
- agent creation and swap-on-success reconfiguration
- message streaming into the visible chat transcript
- step rendering for tables, charts, files, and errors
- session-scoped export payloads and code-log state

The analytical core lives below it in `src/nbadb/chat/*`.

## Lifecycle responsibilities
### Chat start
`chat/chainlit_app.py` initializes session state, sends the settings surface, builds the agent, and attaches tracing callbacks.

### Settings update
The UI rebuilds the agent from updated settings and only swaps the session agent after the rebuild succeeds. Failed reconfiguration leaves the prior agent in place.

### Chat end
The UI calls `cleanup()` on the current agent wrapper and removes persisted session state for the current Chainlit session.

## Rendering contract
### Assistant text
Assistant prose streams into the main `cl.Message`.

### Tool outputs
Tool outputs render as typed steps:
- tables become `cl.Dataframe`
- single Plotly payloads stay interactive
- matplotlib payloads become inline images
- export/share payloads become inline files
- plain stdout and stderr become text blocks

### Session exports
`chat/chainlit_app.py` also owns:
- SQL result download actions
- spreadsheet editing/export actions
- session-code export
- notebook export
- session `code_log` tracking

## Shared-runtime dependencies
The Chainlit layer depends on shared implementation rather than re-defining it:
- `src/nbadb/chat/app/agent.py` for assembled-agent creation
- `src/nbadb/chat/app/preamble.py` for Python helper/export behavior
- `src/nbadb/chat/app/spreadsheet_template.py` for spreadsheet HTML generation
- `src/nbadb/chat/tracing.py` for tracing setup

The app-local `chat/server/*` imports are compatibility surface, not the primary architecture description.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/chat-launcher-runtime-surface|Chat Launcher Runtime Surface]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/export-share-artifacts|Export and Share Artifacts]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| Chainlit hooks, settings flow, session state, message loop, and step rendering | `chat/chainlit_app.py` | canonical UI runtime surface |
| assembled-agent creation and cleanup contract | `src/nbadb/chat/app/agent.py` | shared runtime handoff into the UI |
| shared Python helper and export surface | `src/nbadb/chat/app/preamble.py` | chart, table, export, and share helpers |
| spreadsheet HTML generation | `src/nbadb/chat/app/spreadsheet_template.py` | spreadsheet export/edit surface |
| tracing setup | `src/nbadb/chat/tracing.py` | shared tracing implementation |
| durable artifact tool surface | `chat/mcp_servers/artifacts.py`; `src/nbadb/chat/mcp/artifacts.py` | UI-adjacent persistence lane |
| user-facing app framing | `chat/chainlit.md` | visible app copy and profile framing |
| rendering and action tests | `tests/unit/chat/test_chainlit_rendering.py`; `tests/unit/chat/test_action_helpers.py` | runtime guardrails |
