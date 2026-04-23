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
updated: 2026-04-22
source_count: 7
---

# Prompt Assembly And Capabilities

This note covers how the chat runtime builds two shared session contracts before backend selection:
- the system prompt string
- the `CapabilityManifest`

## Assembly seam
The canonical seam is `src/nbadb/chat/runtime/factory.py`.

`build_runtime_context(settings, profile=...)` is where the runtime:
- resolves the DuckDB path
- loads schema context
- renders the system prompt
- derives the capability manifest

That assembly happens before the backend branch, so Copilot and deepagents start from the same prompt/capability context.

## Prompt construction
`src/nbadb/chat/prompts.py` is the canonical prompt surface.

It has:
- one base warehouse-oriented prompt
- three additive profile overlays:
  - `Quick Stats`
  - `Deep Analysis`
  - `Visualization`

Profile behavior is additive. The runtime does not maintain distinct prompt trees per backend.

## Capability construction
`src/nbadb/chat/runtime/capabilities.py` defines the manifest model and derivation logic.

The manifest reports session-level runtime claims such as:
- SQL and schema access
- semantic catalog availability
- Python analysis and artifact support
- memory and notebook support
- browser-use/web-context flags
- quality-mode toggles such as dual drafting or answer judging
- supported sandbox list

These capabilities are descriptive session metadata. They are not the same thing as final tool attachment.

## Backend handoff
`src/nbadb/chat/app/agent.py` is the main consumer of the assembled runtime context.

It:
- receives `db_path`, `system_prompt`, and `capabilities`
- branches to either the Copilot backend or the deepagents backend
- preserves `capabilities` on the wrapper returned to the higher-level app

The important boundary is:
- prompts and capabilities are centralized
- backends consume them; they do not redefine them

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/profile-settings-surface|Profile Settings Surface]]
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| base prompt template and profile overlays | `src/nbadb/chat/prompts.py` | canonical prompt assembly logic |
| runtime-context assembly | `src/nbadb/chat/runtime/factory.py` | prompt-plus-capabilities seam |
| manifest schema and derivation rules | `src/nbadb/chat/runtime/capabilities.py` | capability policy |
| settings normalization that feeds the manifest | `src/nbadb/chat/runtime/settings.py`; `src/nbadb/chat/access/modes.py` | normalized runtime vocabulary |
| backend handoff and wrapper preservation of capabilities | `src/nbadb/chat/app/agent.py` | runtime assembly consumer |
| schema-context source | `src/nbadb/chat/db.py` | DB and schema helper surface |
| public runtime exports | `src/nbadb/chat/runtime/__init__.py` | runtime package entrypoints |
