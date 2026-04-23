# MCP Server Inventory

## Purpose
- Group the current `chat` MCP server surface: the six built-in stdio servers, the client wiring that launches them, the shared storage backends they depend on, and the runtime split between the deepagents MCP path and the Copilot in-process tool path.

## High-value paths

### MCP server entrypoints
| Path | Inventory role |
| --- | --- |
| `chat/mcp_servers/sql.py` | Read-only DuckDB query server. Exposes `run_sql`, `list_tables`, and `describe_table`, and delegates safety/execution to `server/_safety.py` and `server/_sql_exec.py`. |
| `chat/mcp_servers/catalog.py` | Semantic discovery server over warehouse surfaces. Exposes `search_catalog`, `get_object`, and `recommend_surfaces` backed by `nbadb.chat.catalog`. |
| `chat/mcp_servers/sql_validator.py` | Preflight SQL guardrail server. Exposes `validate_sql`, `explain_sql`, `estimate_query_risk`, and `repair_sql`, with the shared `_validate()` helper also reused by the Copilot backend. |
| `chat/mcp_servers/sandbox.py` | Python analytics execution server. Exposes `run_python`, builds a cached preamble with database/session/helper context, and runs code through sandbox safety plus execution helpers. |
| `chat/mcp_servers/artifacts.py` | Artifact persistence server for reusable outputs. Exposes template/finding save/load/search operations through `ArtifactStore`. |
| `chat/mcp_servers/memory.py` | Local-first memory server for durable preferences and stored analysis trajectories. Exposes preference CRUD plus trajectory save/search through `MemoryStore`. |

### MCP wiring and runtime selection
| Path | Inventory role |
| --- | --- |
| `chat/server/mcp_client.py` | Canonical MCP launcher for the deepagents runtime. Starts built-in servers over `stdio`, conditionally adds `nbadb-artifacts` and `nbadb-memory` when `memory_mode != "off"`, and optionally merges trusted `extra_mcp_servers` unless public demo mode blocks them. |
| `chat/server/agent.py` | Runtime switchboard. Builds the shared runtime context, then sends `provider="copilot"` to the Copilot backend and all other providers to the deepagents plus MCP tool path. |
| `chat/server/copilot_backend.py` | Non-MCP runtime path. Rebuilds an overlapping NBA tool surface in-process with `@define_tool` instead of using `MultiServerMCPClient`, while reusing shared helpers such as `_validate()` from `mcp_servers.sql_validator`. |
| `src/nbadb/chat/runtime/factory.py` | Shared pre-runtime assembly. Resolves the database, builds schema context and system prompt, and constructs the capability manifest before backend selection. |
| `src/nbadb/chat/runtime/settings.py` | Defines the settings that shape MCP wiring and runtime behavior: provider, access mode inference, quality mode, `memory_mode`, `sandbox_mode`, `web_context`, and `extra_mcp_servers`. |
| `src/nbadb/chat/runtime/capabilities.py` | Capability summary model for the current session. Holds feature flags such as `sql`, `semantic_catalog`, `python_analysis`, `artifact_exports`, `memory`, and `supported_sandboxes`. |
| `src/nbadb/chat/access/modes.py` | Maps provider choice into runtime role classes: local models become `AccessMode.LOCAL`, `copilot` becomes `AccessMode.COPILOT`, and cloud APIs default to `AccessMode.BYOK`. |

### Shared persistence and prompt contract
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/artifacts/store.py` | Backing store for the artifacts MCP server and Copilot artifact tools. Persists JSON files plus SQLite/FTS indexes under `~/.nbadb/chat/artifacts`. |
| `src/nbadb/chat/memory/store.py` | Backing store for the memory MCP server and Copilot memory tools. Persists `profile.json` and `trajectories.jsonl` under `~/.nbadb/chat/memory`. |
| `src/nbadb/chat/prompts.py` | Runtime prompt contract that tells the agent which SQL, catalog, validator, sandbox, artifact, and memory tools it should expect to have available. |

## Notes
- `setup_mcp_tools()` always wires four built-ins for the deepagents runtime: `nbadb-sql`, `nbadb-catalog`, `nbadb-sql-validator`, and `nbadb-sandbox`. `nbadb-artifacts` and `nbadb-memory` are added only when `settings.memory_mode != "off"`.
- MCP transport is currently uniform: every built-in server is launched as a Python module with `transport="stdio"` through `MultiServerMCPClient`.
- Runtime roles are intentionally split. `chat/server/agent.py` routes `provider="copilot"` to `create_copilot_agent()` and routes every other provider through deepagents with MCP-backed tools and optional local `web_search`/`web_fetch` tools.
- The Copilot backend does not use `chat/server/mcp_client.py`. It recreates overlapping SQL, catalog, validator, sandbox, artifact, and memory tools directly in `_build_tools()` and then whitelists those tool names inside the Copilot permission handler.
- The two runtimes do not expose identical tool surfaces today. The MCP path gets the full server surface, including `explain_sql`, `estimate_query_risk`, `list_templates`, `search_findings`, `list_preferences`, and `forget_memory`. The Copilot tool list is narrower and currently omits those operations.
- Session handling is asymmetric by design. `sandbox.py`, `artifacts.py`, and `memory.py` all accept a `session_id`, but only some persistence is truly session-scoped: sandbox session state is directed into `~/.nbadb/session/<session_id>`, saved findings are tagged with `session_id` metadata, preferences remain global in `profile.json`, and trajectories are append-only rows labeled with `session_id`.
- The capability manifest is descriptive rather than authoritative runtime wiring. It reports broad feature availability across sessions, while actual tool availability depends on backend selection, `memory_mode`, `web_context`, and the narrower Copilot tool registration set.
- `build_capability_manifest()` currently returns the full `(local, daytona, e2b)` sandbox tuple regardless of the selected `sandbox_mode`; the current code distinguishes the chosen mode elsewhere, not by shrinking `supported_sandboxes`.
- The prompt contract in `src/nbadb/chat/prompts.py` is not fully aligned with the richest MCP surface. It references `search_findings`, `estimate_query_risk`, and related tool families conceptually, but the exact availability still depends on which runtime path is active.

## Planned wiki coverage
- `wiki/topics/chat-mcp-server-surface.md`
- `wiki/topics/chat-mcp-client-wiring.md`
- `wiki/topics/chat-runtime-role-distinctions.md`
- `wiki/topics/chat-artifact-and-memory-persistence.md`

## Provenance
- `chat/mcp_servers/sql.py`
- `chat/mcp_servers/catalog.py`
- `chat/mcp_servers/sql_validator.py`
- `chat/mcp_servers/sandbox.py`
- `chat/mcp_servers/artifacts.py`
- `chat/mcp_servers/memory.py`
- `chat/server/mcp_client.py`
- `chat/server/agent.py`
- `chat/server/copilot_backend.py`
- `src/nbadb/chat/runtime/factory.py`
- `src/nbadb/chat/runtime/settings.py`
- `src/nbadb/chat/runtime/capabilities.py`
- `src/nbadb/chat/access/modes.py`
- `src/nbadb/chat/artifacts/store.py`
- `src/nbadb/chat/memory/store.py`
- `src/nbadb/chat/prompts.py`
