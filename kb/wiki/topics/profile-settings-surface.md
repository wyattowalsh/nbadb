---
title: Profile Settings Surface
tags:
  - kb
  - topics
  - chat
  - chainlit
  - runtime
  - settings
aliases:
  - Chat Profile And Settings Surface
  - Provider Model Settings Surface
kind: concept
status: active
updated: 2026-04-22
source_count: 9
---

# Profile Settings Surface

This note maps the visible and runtime settings surface for the chat app: Chainlit profiles, the settings panel, provider/model selection, and the shared settings model.

## Surface map
| Surface | Owned by | What it controls |
| --- | --- | --- |
| Chat profile picker | `chat/chainlit_app.py` | visible profiles, starters, and per-profile session prep |
| Gear-panel settings | `chat/chainlit_app.py` | provider, model, temperature, quality, memory, sandbox, tracing, and web-context toggles |
| Prompt profile overlays | `src/nbadb/chat/prompts.py` | additive instructions for `Quick Stats`, `Deep Analysis`, and `Visualization` |
| Runtime settings model | `src/nbadb/chat/runtime/settings.py` | defaults, env/JSON loading, and normalization |
| Provider/model factory | `src/nbadb/chat/providers/factory.py` | non-Copilot client construction |
| Chainlit app config | `chat/.chainlit/config.toml` | UI chrome, timeout, and feature flags |

## Profiles
The visible profiles are:
- `Quick Stats`
- `Deep Analysis`
- `Visualization`

The split is intentionally narrow:
- `chat/chainlit_app.py` owns the visible names, descriptions, icons, and starters
- `src/nbadb/chat/prompts.py` owns the additive prompt overlays
- only `Quick Stats` currently changes runtime settings directly by lowering temperature

## Provider and model choices
Provider choice matters because runtime branching happens after settings normalization:
- `copilot` uses the dedicated Copilot backend
- other providers use the shared provider factory path
- access mode is derived from provider choice in `src/nbadb/chat/access/modes.py`

Model selection is free-form text passed through the provider client path.

## Shared settings model
`src/nbadb/chat/runtime/settings.py` is the canonical settings contract.

It owns:
- defaults
- `NBADB_CHAT_` environment loading
- `~/.nbadb/chat.json` loading
- normalization such as access-mode derivation and quality-mode implications

The app-local `chat/server/config.py` file is only a compatibility re-export, not a second settings model.

## Related notes
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/access-mode-contract|Access Mode Contract]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| visible profiles, settings panel, and session update flow | `chat/chainlit_app.py` | canonical UI/runtime surface |
| additive profile prompt instructions | `src/nbadb/chat/prompts.py` | profile-specific prompt text |
| runtime defaults, env/JSON loading, and normalization rules | `src/nbadb/chat/runtime/settings.py` | canonical settings contract |
| provider enum and capability vocabulary | `src/nbadb/chat/runtime/capabilities.py` | normalized runtime vocabulary |
| provider-to-access-mode mapping | `src/nbadb/chat/access/modes.py` | access-mode derivation |
| non-Copilot model client construction | `src/nbadb/chat/providers/factory.py` | provider client path |
| backend assembly split | `src/nbadb/chat/app/agent.py`; `src/nbadb/chat/app/copilot_backend.py` | Copilot vs deepagents |
| Chainlit shell config | `chat/.chainlit/config.toml` | app-shell config |
| app-local guidance and config shim | `chat/chainlit.md`; `chat/server/config.py` | user-facing framing plus compatibility re-export |
