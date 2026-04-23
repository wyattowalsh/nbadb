# Chat Service Layer Inventory

## Purpose
- Grouped internal extract manifest for the shared chat service layer below agent assembly.
- Capture how chat launch/bootstrap, notebook setup, tracing, catalog inference, memory persistence, access-mode routing, capability exposure, and SQL validation/explanation/repair are split across the current Python surface.

## High-value paths

### Launch and notebook bootstrap
| Path | Service role | Key behaviors |
| --- | --- | --- |
| `src/nbadb/chat/launcher.py` | Local Chainlit launcher and readiness helper. | Resolves `chat`, builds environment overrides, chooses `uv run chainlit` for foreground execution, falls back to `python -m chainlit` for spawned subprocesses, and polls the HTTP endpoint until ready. |
| `src/nbadb/chat/notebook.py` | Notebook-side bootstrap for reproducible chat sessions. | Detects Kaggle vs local working dirs, reuses an existing `chat` checkout when present, otherwise clones a pinned repo ref, copies DuckDB locally when needed, and installs chat dependencies from the chat app `pyproject.toml`. |

### Tracing and runtime capability gating
| Path | Service role | Key behaviors |
| --- | --- | --- |
| `src/nbadb/chat/tracing.py` | Shared tracing setup entrypoint. | Serializes setup behind a thread lock, no-ops when tracing is disabled, enables LangSmith via environment flags, and returns Langfuse callback handlers only when the package and keys are available. |
| `src/nbadb/chat/access/modes.py` | Provider-to-access-mode normalization. | Maps `ollama` and `lmstudio` to `local`, `copilot` to `copilot`, and sends all other providers through the `byok` path. |
| `src/nbadb/chat/runtime/capabilities.py` | Capability manifest builder for runtime/tool planning. | Defines provider, quality, semantic, memory, and sandbox enums, then emits a `CapabilityManifest` that toggles browser use, dual-SQL drafting, answer judging, notebook generation, and advertised sandbox support. |

### Semantic catalog and SQL safety services
| Path | Service role | Key behaviors |
| --- | --- | --- |
| `src/nbadb/chat/catalog/service.py` | Semantic surface introspection and search over warehouse tables. | Inspects DuckDB `information_schema`, infers family, grain, entities, join keys, measures, time dimensions, aliases, usage guidance, pitfalls, and example questions, then ranks matches for search/recommend flows. |
| `src/nbadb/chat/sql/service.py` | Read-only SQL validation, explain, risk, and repair helpers. | Extracts referenced tables, applies `ReadOnlyGuard`, verifies table existence against the semantic catalog, runs `EXPLAIN` in read-only DuckDB with external access disabled, adds grain/join warnings, estimates risk, and suggests repair candidates from catalog search. |

### Memory persistence
| Path | Service role | Key behaviors |
| --- | --- | --- |
| `src/nbadb/chat/memory/store.py` | Persistent preference and trajectory store for chat memory. | Creates a local SQLite store under `~/.nbadb/chat/memory`, migrates legacy `profile.json` and `trajectories.jsonl` payloads into tables, upserts preference records, appends trajectory records, and performs lightweight token-based trajectory search without FTS. |

## Notes
- `launcher.py` separates foreground and background launch strategies on purpose: the direct runner insists on `uv`, while spawned processes use the current Python interpreter and suppress stdout/stderr noise.
- `notebook.py` is tuned for notebook reproducibility rather than general deployment. It prefers an already checked out `chat` tree, otherwise clones a detached commit and installs dependencies directly from the app's declared dependency sets.
- `tracing.py` is the real implementation surface; `chat/server/tracing.py` is only a compatibility wrapper that re-exports `setup_tracing` after adding `src/` to `sys.path`.
- `access_mode_from_provider()` currently infers only `local`, `copilot`, and `byok`. `AccessMode.OPENAI_LOGIN` exists for downstream capability logic, but this helper does not derive it from provider strings.
- `build_capability_manifest()` makes browser access conditional on `copilot` or `openai-login`, makes careful mode enable dual-SQL drafting, disables answer judging only for fast mode, and currently returns the same advertised sandbox tuple regardless of the requested sandbox branch.
- `catalog/service.py` recomputes catalog objects directly from DuckDB metadata on each list/search/recommend request; there is no cache layer in this service module.
- `sql/service.py` never executes the user query for results. Its validation/explanation path stops at guarded parsing plus DuckDB `EXPLAIN`, then layers semantic warnings and repair suggestions from catalog metadata.
- `memory/store.py` persists structured Pydantic records as JSON blobs inside SQLite rows. Search is simple lexical scoring across archetype, grain, chosen surfaces, tags, repair notes, artifact kinds, hashes, replay handles, and raw payload text.

## Planned wiki coverage
- `kb/wiki/topics/chat-launcher-runtime-surface.md`
- `kb/wiki/topics/chat-notebook-bootstrap.md`
- `kb/wiki/topics/chat-tracing-surface.md`
- `kb/wiki/topics/access-mode-contract.md`
- `kb/wiki/topics/semantic-catalog-service.md`
- `kb/wiki/topics/sql-validator-service.md`
- `kb/wiki/topics/memory-store-internals.md`

## Provenance
- `src/nbadb/chat/launcher.py`
- `src/nbadb/chat/notebook.py`
- `src/nbadb/chat/tracing.py`
- `chat/server/tracing.py`
- `src/nbadb/chat/catalog/service.py`
- `src/nbadb/chat/memory/store.py`
- `src/nbadb/chat/access/modes.py`
- `src/nbadb/chat/runtime/capabilities.py`
- `src/nbadb/chat/sql/service.py`
