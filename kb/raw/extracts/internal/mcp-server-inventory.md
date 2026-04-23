# MCP Server Inventory

## Purpose
- Group the current v1 MCP server surface: the app-local stdio entrypoints under `chat/mcp_servers/`, the shared implementations under `src/nbadb/chat/mcp/`, the client wiring that launches them, and the runtime split between the deepagents MCP path and the Copilot in-process tool path.

## High-value paths

### MCP server entrypoints
| Path | Inventory role |
| --- | --- |
| `chat/mcp_servers/sql.py` | App-local stdio entrypoint for the SQL MCP surface. |
| `chat/mcp_servers/catalog.py` | App-local stdio entrypoint for semantic catalog tools. |
| `chat/mcp_servers/sql_validator.py` | App-local stdio entrypoint for SQL validation and repair tools. |
| `chat/mcp_servers/sandbox.py` | App-local stdio entrypoint for Python analysis and export helpers. |
| `chat/mcp_servers/artifacts.py` | App-local stdio entrypoint for artifact persistence tools. |
| `chat/mcp_servers/memory.py` | App-local stdio entrypoint for memory and trajectory tools. |

### Shared MCP implementations
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/mcp/sql.py` | Canonical SQL MCP implementation over the shared read-only SQL executor. |
| `src/nbadb/chat/mcp/catalog.py` | Canonical semantic-catalog MCP implementation. |
| `src/nbadb/chat/mcp/sql_validator.py` | Canonical SQL validator MCP implementation. |
| `src/nbadb/chat/mcp/sandbox.py` | Canonical sandbox MCP implementation and helper contract. |
| `src/nbadb/chat/mcp/artifacts.py` | Canonical artifact MCP implementation. |
| `src/nbadb/chat/mcp/memory.py` | Canonical memory MCP implementation. |

### MCP wiring and runtime selection
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/app/mcp_client.py` | Canonical MCP launcher for the deepagents runtime. Starts built-in servers over `stdio`, conditionally adds `nbadb-artifacts` and `nbadb-memory`, and optionally merges trusted `extra_mcp_servers`. |
| `src/nbadb/chat/app/agent.py` | Runtime switchboard. Builds the shared runtime context, then sends `provider="copilot"` to the Copilot backend and all other providers to the deepagents plus MCP tool path. |
| `src/nbadb/chat/app/copilot_backend.py` | Non-MCP runtime path. Rebuilds an overlapping NBA tool surface in-process with direct tool registration instead of `MultiServerMCPClient`. |
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
- `chat/mcp_servers/*` is the canonical app-local stdio surface, but the shared implementation logic lives in `src/nbadb/chat/mcp/*`.
- `setup_mcp_tools()` always wires four built-ins for the deepagents runtime: `nbadb-sql`, `nbadb-catalog`, `nbadb-sql-validator`, and `nbadb-sandbox`. `nbadb-artifacts` and `nbadb-memory` are added only when `settings.memory_mode == "persistent"`.
- MCP transport is currently uniform: every built-in server is launched as a Python module with `transport="stdio"` through `MultiServerMCPClient`.
- Runtime roles are intentionally split. `src/nbadb/chat/app/agent.py` routes `provider="copilot"` to `create_copilot_agent()` and routes every other provider through deepagents with MCP-backed tools and optional local web tools.
- The Copilot backend does not use `src/nbadb/chat/app/mcp_client.py`. It recreates overlapping SQL, catalog, validator, sandbox, artifact, and memory tools directly in-process.
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
- `src/nbadb/chat/mcp/sql.py`
- `src/nbadb/chat/mcp/catalog.py`
- `src/nbadb/chat/mcp/sql_validator.py`
- `src/nbadb/chat/mcp/sandbox.py`
- `src/nbadb/chat/mcp/artifacts.py`
- `src/nbadb/chat/mcp/memory.py`
- `src/nbadb/chat/app/mcp_client.py`
- `src/nbadb/chat/app/agent.py`
- `src/nbadb/chat/app/copilot_backend.py`
- `src/nbadb/chat/runtime/factory.py`
- `src/nbadb/chat/runtime/settings.py`
- `src/nbadb/chat/runtime/capabilities.py`
- `src/nbadb/chat/access/modes.py`
- `src/nbadb/chat/artifacts/store.py`
- `src/nbadb/chat/memory/store.py`
- `src/nbadb/chat/prompts.py`
