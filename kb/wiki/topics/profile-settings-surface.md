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
updated: 2026-04-15
source_count: 10
---

# Profile Settings Surface

This note maps the user-visible and runtime-visible settings surface for `chat/`: Chainlit chat profiles, the gear-panel settings, provider/model selection, and the config files that shape session behavior before and after agent creation.

## Surface map
| Surface | Owned by | What it controls |
| --- | --- | --- |
| Chat profile picker | `chat/chainlit_app.py` | prompt mode plus profile-specific starters |
| Gear-panel settings | `chat/chainlit_app.py` | provider, model, temperature, quality, memory, sandbox, tracing, and related runtime toggles |
| Prompt profile overlays | `src/nbadb/chat/prompts.py` | additive instructions for `Quick Stats`, `Deep Analysis`, and `Visualization` |
| Runtime settings model | `src/nbadb/chat/runtime/settings.py` | defaults, env/JSON loading, and normalization |
| Provider/model factory | `chat/server/providers/factory.py` | which model client is created for non-Copilot sessions |
| Chainlit app config | `chat/.chainlit/config.toml` | UI chrome, session timeout, feature flags, and theme |

## Chainlit profiles
The visible chat profiles are:
- `Quick Stats`
- `Deep Analysis`
- `Visualization`

Their split is intentionally narrow:
- `chat/chainlit_app.py` defines their display names, descriptions, icons, and starter prompts.
- `src/nbadb/chat/prompts.py` appends a small profile-specific instruction block onto one shared base system prompt.
- Only `Quick Stats` currently changes runtime settings in addition to prompt text: `_prepare_session_settings(...)` lowers `temperature` to `0.05`.

Current profile intent:
- `Quick Stats`: concise SQL-first answers, tables preferred, skip Python and charts unless asked.
- `Deep Analysis`: allow multi-step analysis, advanced metrics, and historical context.
- `Visualization`: include a chart whenever the data shape supports it.

Important boundary: these are UI and prompt profiles, not the memory-layer `ProfileRecord` concept.

## Gear-panel settings
`_send_settings_panel(...)` renders the Chainlit settings form and exposes these runtime fields:
- `provider`
- `model`
- `api_key`
- `temperature`
- `quality_mode`
- `semantic_mode`
- `memory_mode`
- `memory_promotion`
- `sandbox_mode`
- `web_context`
- `dual_sql_drafting`
- `answer_judge`
- `trace_capture`
- `base_url`

Settings updates are guarded rather than applied blindly:
- `@cl.on_settings_update` rebuilds `ChatSettings` from the incoming snapshot.
- The runtime tries to create a fresh agent with the new settings.
- The session swaps to the new agent only after rebuild succeeds.
- If rebuild fails, the previous agent stays active.

That means the settings panel is a live reconfiguration surface, not just a passive preferences form.

## Provider and model choices
The visible provider options are:
- `openai`
- `anthropic`
- `google`
- `ollama`
- `lmstudio`
- `copilot`
- `custom`

How provider choice behaves:
- `copilot` is a special runtime path. `chat/server/agent.py` bypasses the LangChain model factory and uses the dedicated Copilot backend.
- All other providers go through `chat/server/providers/factory.py`.
- `openai` and `custom` both use `ChatOpenAI`; `custom` exists for OpenAI-compatible endpoints with a user-supplied `base_url`.
- `anthropic` uses `ChatAnthropic`.
- `google` uses `ChatGoogleGenerativeAI`.
- `ollama` uses `ChatOllama` and defaults to `http://localhost:11434` when `base_url` is unset.
- `lmstudio` uses the OpenAI-compatible client and defaults to `http://localhost:1234/v1` with a placeholder API key.

Model selection is free-form text in the UI. The app does not constrain model IDs beyond passing the chosen string into the selected provider client.

## Runtime settings model
`ChatSettings` is the canonical session settings object.

Key defaults:
- provider: `openai`
- model: `gpt-4.1`
- temperature: `0.1`
- quality mode: `balanced`
- semantic mode: `semantic-first`
- memory mode: `persistent`
- sandbox mode: `local`
- web context: `true`
- answer judge: `true`

Load order and storage:
- environment variables with the `NBADB_CHAT_` prefix
- JSON config at `~/.nbadb/chat.json`
- direct constructor values

Normalization rules matter:
- `duckdb_path` is expanded and resolved.
- `access_mode` is derived from the provider when omitted.
- `quality_mode=careful` forces `dual_sql_drafting=true`.
- `quality_mode=fast` forces `answer_judge=false`.

Access-mode mapping is provider-driven:
- `ollama` and `lmstudio` map to `local`
- `copilot` maps to `copilot`
- everything else currently maps to `byok`

## Config files and runtime shims
### `~/.nbadb/chat.json`
This is the durable local config file for `ChatSettings`. It is the main place to persist chat runtime defaults outside the UI session.

### `chat/.chainlit/config.toml`
This is the Chainlit app config, separate from `ChatSettings`. It controls app shell behavior such as:
- `session_timeout = 7200`
- telemetry disabled
- markdown/math and message-edit features
- wide layout, dark theme, and custom CSS/avatar
- `cot = "tool_call"` for Chainlit thought rendering

### `chat/chainlit.md`
This is the welcome copy, not executable config. It teaches users to use the gear icon for provider/model changes and the profile picker for analysis mode.

### `chat/server/config.py`
This is only a compatibility shim that re-exports `ChatSettings` from `src/nbadb/chat/runtime/settings.py`. It does not define a separate config model.

## Interaction rules
- Profiles and provider/model choices stay independent until agent creation.
- `build_runtime_context(settings, profile=...)` is the seam where both come together.
- Profile choice changes prompt instructions for all three profiles, but runtime-setting changes are currently asymmetric because only `Quick Stats` adjusts temperature.
- Capability flags are derived from normalized settings, not from the Chainlit profile name.
- `web_context` affects whether local `web_search` and `web_fetch` tools are attached on the deepagents path.

## Related notes
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/visualization-surface|Visualization Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| visible profiles, settings panel fields, session update flow, and `Quick Stats` temperature override | `chat/chainlit_app.py` | canonical Chainlit UI/runtime surface |
| additive profile prompt instructions | `src/nbadb/chat/prompts.py` | canonical `Quick Stats`, `Deep Analysis`, and `Visualization` profile text |
| runtime defaults, `NBADB_CHAT_` prefix, `~/.nbadb/chat.json`, and normalization rules | `src/nbadb/chat/runtime/settings.py` | canonical settings contract |
| provider enum, quality/memory/sandbox enums, and capability derivation | `src/nbadb/chat/runtime/capabilities.py` | confirms normalized runtime vocabulary |
| provider-to-access-mode mapping | `src/nbadb/chat/access/modes.py` | shows `local`, `copilot`, and `byok` derivation |
| non-Copilot model client construction and provider-specific defaults | `chat/server/providers/factory.py` | canonical LangChain model factory |
| Copilot-vs-deepagents branch and prompt/settings handoff | `chat/server/agent.py` | canonical backend assembly split |
| Chainlit shell config such as timeout, theme, layout, and features | `chat/.chainlit/config.toml` | app-shell config, separate from `ChatSettings` |
| user-facing guidance to use the gear icon and profile picker | `chat/chainlit.md` | welcome copy and UX framing |
| app-local config re-export shim | `chat/server/config.py` | confirms there is no second settings model |
