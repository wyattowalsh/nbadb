---
title: Memory Store Internals
tags:
  - kb
  - topics
  - chat
  - memory
  - internals
aliases:
  - Durable Memory Store
  - Local Memory Store
kind: concept
status: active
updated: 2026-04-15
source_count: 8
---

# Memory Store Internals

This note covers the durable local memory lane behind chat preferences and analytical trajectories, and how that lane relates to the broader record models and MCP-facing memory tools.

## Mental model
- `MemoryStore` is the durable local-first store under `src/nbadb/chat/memory/store.py`.
- Its active persistence scope is narrow: `ProfileRecord` for preferences and `TrajectoryRecord` for saved successful workflows.
- `FindingRecord` and `TemplateRecord` live in the same model module, but their durable writes belong to `ArtifactStore`, not `MemoryStore`.
- The MCP memory surface is a thin wrapper over `MemoryStore`, not a second storage system.

## 1. Storage layout

### Root and primary file
- Default root: `~/.nbadb/chat/memory`.
- Primary durable file: `memory.sqlite3`.
- Unlike the artifact lane, the memory lane does not maintain active bucket subdirectories for current writes.

### SQLite tables
| Table | Key columns | Purpose |
| --- | --- | --- |
| `preferences` | `key`, `record_json`, `updated_at` | one upserted preference record per logical key |
| `trajectories` | `id`, `session_id`, `archetype`, `record_json`, `created_at` | append-only history of saved trajectories |

### Indexes
- `idx_memory_trajectories_created_at` on `trajectories(created_at DESC)`.
- `idx_memory_trajectories_archetype` on `trajectories(archetype)`.
- There is no dedicated full-text index; search is in-memory after row load.

### Legacy migration inputs
- `profile.json` is treated as the legacy preference source.
- `trajectories.jsonl` is treated as the legacy trajectory source.
- Migration only runs when the target table is still empty and the legacy file exists.

## 2. Record model map
| Model | Defined in | Durable owner | Main fields | Notes |
| --- | --- | --- | --- | --- |
| `ProfileRecord` | `src/nbadb/chat/memory/models.py` | `MemoryStore.preferences` | `key`, `value`, `session_id`, `notes`, timestamps, `promotion_mode` | canonical preference record |
| `TrajectoryRecord` | `src/nbadb/chat/memory/models.py` | `MemoryStore.trajectories` | `session_id`, `archetype`, `payload`, `chosen_surfaces`, `grain`, `sql_hash`, `repair_notes`, `artifact_kinds`, `tags`, replay metadata, timestamps | canonical saved workflow record |
| `FindingRecord` | `src/nbadb/chat/memory/models.py` | `ArtifactStore.findings` | `title`, `summary`, `metadata`, normalized entities/metrics/tags, replay metadata, timestamps | shared model vocabulary, not stored by `MemoryStore` |
| `TemplateRecord` | `src/nbadb/chat/memory/models.py` | `ArtifactStore.templates` | `name`, `summary`, `payload`, `tags`, replay metadata, timestamps | shared model vocabulary, not stored by `MemoryStore` |

Important boundary: the memory package exports all four models, but the store implementation only initializes and queries the `preferences` and `trajectories` tables.

## 3. Normalization rules

### Shared base behavior
- `ChatStoreRecord` sets `extra="ignore"`, so unknown fields are tolerated and dropped during validation.
- `_normalize_text_tuple(...)` is the common tuple normalizer.
- It accepts `None`, a single string, or tuple/list/set inputs.
- It strips whitespace, drops empty values, coerces members to strings, and returns tuples.

### `ProfileRecord`
- No custom validator.
- Stored fields are whatever the caller supplies plus timestamps assembled by `MemoryStore.remember_preference(...)`.

### `FindingRecord`
- Ensures `metadata` is a dict.
- Pulls `entities`, `metrics`, and `tags` from top-level fields first, then falls back to `metadata`.
- Derives `source_sql_hash` from `metadata.source_sql_hash` or `metadata.sql_hash`.
- Derives `replay_handle`, `session_id`, `promotion_mode`, and default `confidence` from metadata when absent at the top level.
- Backfills `created_at` from `updated_at` when only one timestamp is present.

### `TemplateRecord`
- Ensures `payload` is a dict.
- Pulls `tags` from top-level fields first, then from `payload.tags`.
- Derives `source_sql_hash`, `replay_handle`, `session_id`, and `promotion_mode` from payload when absent at the top level.
- Backfills `created_at` from `updated_at` when needed.

### `TrajectoryRecord`
- Ensures `payload` is a dict.
- Pulls `chosen_surfaces`, `repair_notes`, `artifact_kinds`, and `tags` from top-level fields first, then from payload.
- Derives `grain`, `sql_hash`, `replay_handle`, `success`, `confidence`, and `promotion_mode` from payload when absent at the top level.
- Accepts either `sql_hash` or `source_sql_hash` in payload.
- Backfills `updated_at` from `created_at` when only one timestamp exists.

## 4. Persistence behavior

### Preferences
- `remember_preference(key, value, ...)` performs an upsert on `preferences.key`.
- It preserves the existing `created_at` when overwriting a key.
- It also carries forward stored `session_id` and `notes` if the caller omits them.
- The canonical durable payload is `record_json`, serialized with sorted JSON keys.
- `list_preferences()` returns all validated records ordered by `key`.
- `forget_preference(key)` deletes one preference row.

### Trajectories
- `save_trajectory(archetype, payload, session_id)` is append-only.
- Each save writes a new row with duplicated selector columns (`session_id`, `archetype`, `created_at`) plus canonical `record_json`.
- `created_at` prefers `payload["created_at"]`; otherwise it uses current UTC time.
- `updated_at` prefers `payload["updated_at"]`; otherwise it also uses current UTC time.
- There is no trajectory-delete API in `MemoryStore` or the MCP wrapper.

### Legacy migration behavior
- Preference migration reads `profile.json` and converts either scalar values or dict envelopes into `ProfileRecord`s.
- Trajectory migration reads one JSON object per line from `trajectories.jsonl` and wraps each into a `TrajectoryRecord`.
- Migration is intentionally one-shot in practice because it short-circuits once destination tables already have rows.

## 5. Search behavior
- Only trajectories are searchable.
- Blank queries return `[]` immediately.
- Search loads all stored trajectories ordered by `created_at DESC`, validates them into `TrajectoryRecord`s, then scores them in Python.

### Match inputs
- `primary_text` is built from `archetype`, `grain`, and `chosen_surfaces`.
- `search_text` extends that with `tags`, `repair_notes`, `artifact_kinds`, `sql_hash`, `replay_handle`, and the serialized `payload`.

### Scoring
- Exact query substring in `primary_text`: `+5`.
- Exact query substring in `search_text`: `+3`.
- Per token from `[a-z0-9_]+` found in `primary_text`: `+2`.
- Per token found only in `search_text`: `+1`.
- Non-positive scores are discarded.
- Final ordering is `(score, created_at)` descending, then truncated to `limit`.

Practical implication: search favors archetype and chosen-surface matches first, but it can still retrieve trajectories by SQL hash, replay handle, tags, repair notes, or any searchable payload fragment.

## 6. Relationship to MCP memory surfaces

### `nbadb-memory`
- `chat/mcp_servers/memory.py` exposes `MemoryStore` through a FastMCP server named `nbadb-memory`.
- Tool mapping is direct:

| MCP tool | Store method | Notes |
| --- | --- | --- |
| `remember_preference` | `remember_preference` | MCP surface currently passes only `key` and `value` |
| `list_preferences` | `list_preferences` | returns the whole preference map |
| `save_trajectory` | `save_trajectory` | injects `SESSION_ID` from the server process args |
| `search_trajectories` | `search_trajectories` | exposes `limit` |
| `forget_memory` | `forget_preference` | deletes one preference key |

### Exposure boundary
- `chat/server/mcp_client.py` only registers `nbadb-memory` when `memory_mode != "off"`.
- The deepagents runtime therefore sees memory as an optional MCP capability, not a mandatory core tool.

### Important distinction from artifacts
- `nbadb-memory` does not expose tools for `FindingRecord` or `TemplateRecord`.
- Those records are persisted through `nbadb-artifacts` and `ArtifactStore`, even though they share the same model module.
- The in-process Copilot backend mirrors this same split: memory tools call `MemoryStore`, while artifact tools call `ArtifactStore`.

## Related notes
- [[wiki/topics/artifact-store-internals|Artifact Store Internals]]
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| memory root path, SQLite file, table layout, indexes, legacy migration triggers, upsert/append semantics, and trajectory search scoring | `src/nbadb/chat/memory/store.py` | canonical durable memory implementation |
| shared record classes and normalization rules for `ProfileRecord`, `FindingRecord`, `TemplateRecord`, and `TrajectoryRecord` | `src/nbadb/chat/memory/models.py` | canonical record schema and validator behavior |
| exported memory package surface | `src/nbadb/chat/memory/__init__.py` | confirms that the package exports more model types than the store itself persists |
| MCP server name, tool mapping, and `SESSION_ID` handling | `chat/mcp_servers/memory.py` | canonical MCP-facing memory surface |
| MCP registration gate under `memory_mode != "off"` | `chat/server/mcp_client.py` | runtime condition for exposing the memory server to the agent |
| in-process backend mirror of memory tools | `chat/server/copilot_backend.py` | shows the same storage contract without MCP subprocesses |
| finding/template durable ownership and reuse of shared models | `src/nbadb/chat/artifacts/store.py` | confirms that `FindingRecord` and `TemplateRecord` persist through the artifact lane |
| observed round-trip behavior for preferences, trajectories, hashes, and chosen-surface search | `tests/unit/chat/test_catalog_and_memory_services.py` | test evidence for intended persistence and retrieval behavior |
