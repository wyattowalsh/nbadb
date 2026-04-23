# Prompt And Profile Manifest

## Purpose
- Group the internal prompt and profile surface for the chat app: shared prompt construction, Chainlit profile selection, runtime settings and capability flags, and the provider/profile flow that turns session choices into an initialized agent.

## High-value paths

### Prompt sources and wrappers
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/prompts.py` | Canonical system prompt template plus the three profile overlays: `Quick Stats`, `Deep Analysis`, and `Visualization`. |
| `chat/server/prompts.py` | Thin compatibility wrapper that exposes `build_system_prompt()` from the shared `src/` module for the `chat/server` runtime. |
| `src/nbadb/chat/runtime/factory.py` | Resolves the database, builds schema context, renders the profile-aware system prompt, and constructs the capability manifest in one place. |

### Runtime settings and capability models
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/runtime/settings.py` | Defines `ChatSettings`, the `NBADB_CHAT_` settings surface, provider/model/temperature/quality toggles, web context flag, sandbox mode, and post-validation normalization. |
| `src/nbadb/chat/runtime/capabilities.py` | Defines `ProviderName`, `QualityMode`, `SemanticMode`, `MemoryMode`, `SandboxMode`, and the `CapabilityManifest` used to describe what the current session can do. |
| `src/nbadb/chat/access/modes.py` | Maps provider choice to access mode, including the special `copilot` branch and local-provider handling for `ollama` and `lmstudio`. |
| `chat/server/config.py` | Compatibility wrapper that re-exports the shared runtime settings into the app-local server package. |

### Chat profile surfaces
| Path | Inventory role |
| --- | --- |
| `chat/chainlit_app.py` | Declares the visible Chainlit chat profiles, their descriptions/icons/starters, applies per-profile session tweaks, persists the selected profile in session state, and recreates the agent after settings changes. |
| `chat/chainlit.md` | User-facing landing copy that tells users to pick a profile and change providers/models via the settings gear. |
| `src/nbadb/chat/memory/models.py` | Defines `ProfileRecord` for saved memory/preferences; separate from the prompt profile concept but easy to confuse when tracing "profile" usage. |

### Provider and agent assembly flow
| Path | Inventory role |
| --- | --- |
| `chat/server/agent.py` | Entry point that takes `settings` plus optional `profile`, builds runtime context, then chooses `copilot` vs deepagents assembly while carrying the capability manifest into the wrapper. |
| `chat/server/providers/factory.py` | LangChain model factory for non-copilot providers: `openai`, `custom`, `anthropic`, `google`, `ollama`, and `lmstudio`. |
| `chat/server/copilot_backend.py` | Dedicated runtime path when `provider=copilot`; consumes the already-built system prompt instead of going through the LangChain factory. |
| `src/nbadb/chat/__init__.py` | Re-export surface that makes prompt, runtime, capability, and settings helpers available from the package root. |

## Notes
- Prompt construction is centralized: `build_runtime_context()` always resolves the DuckDB path, derives schema context, calls `build_system_prompt(schema_context, profile=profile)`, then derives `CapabilityManifest` from normalized settings.
- The shared prompt module is intentionally minimal. It carries one warehouse-oriented base prompt and three additive profile blocks rather than distinct prompt files per provider or UI mode.
- Profile behavior is asymmetric today: the prompt overlay changes for all three profiles, but only `Quick Stats` also changes runtime settings by lowering `temperature` to `0.05` in `_prepare_session_settings()`.
- Provider selection and profile selection stay independent until agent creation. The Chainlit UI captures the chosen profile, settings updates capture the chosen provider/model, and `create_nba_agent()` receives both so prompt rendering and backend selection happen together.
- `ChatSettings._normalize()` derives `access_mode` from the provider when omitted, enables `dual_sql_drafting` for `careful`, and disables `answer_judge` for `fast`; `build_capability_manifest()` mirrors those quality-derived flags into the runtime capability summary.
- The capability manifest currently marks most features as available across providers, but `browser_use` is gated by access mode and the deepagents runtime only adds `web_search` and `web_fetch` when `settings.web_context` is true.
- `chat/server/prompts.py` and `chat/server/config.py` exist to keep the `chat/server` package importable without duplicating the shared prompt/settings implementation.
- There are two different "profile" concepts in the codebase: prompt/UI analysis profiles (`Quick Stats`, `Deep Analysis`, `Visualization`) and memory `ProfileRecord` entries used for stored preferences.

## Planned wiki coverage
- `wiki/topics/chat-prompt-contract.md`
- `wiki/topics/chat-profiles-and-session-modes.md`
- `wiki/topics/chat-runtime-settings.md`
- `wiki/topics/provider-selection-and-agent-assembly.md`

## Provenance
- `src/nbadb/chat/prompts.py`
- `chat/server/prompts.py`
- `src/nbadb/chat/runtime/factory.py`
- `src/nbadb/chat/runtime/settings.py`
- `src/nbadb/chat/runtime/capabilities.py`
- `src/nbadb/chat/access/modes.py`
- `chat/server/config.py`
- `chat/chainlit_app.py`
- `chat/chainlit.md`
- `chat/server/agent.py`
- `chat/server/providers/factory.py`
- `chat/server/copilot_backend.py`
- `src/nbadb/chat/memory/models.py`
- `src/nbadb/chat/__init__.py`
