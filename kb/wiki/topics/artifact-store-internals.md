---
title: Artifact Store Internals
tags:
  - kb
  - topics
  - chat
  - artifacts
  - internals
aliases:
  - Artifact Persistence Internals
  - Chat Artifact Store
kind: concept
status: active
updated: 2026-04-14
source_count: 10
---

# Artifact Store Internals

This note covers the durable artifact lane behind chat templates and findings, and how that lane differs from the chat app's export/share helpers.

## Mental model
- There are two adjacent artifact systems in chat.
- `ArtifactStore` is the durable local store. It writes JSON files under `~/.nbadb/chat/artifacts` and is meant for cross-session reuse.
- Export/share helpers are transient delivery surfaces. They emit file payloads back to the UI or keep lightweight result payloads in Chainlit session state.
- Nothing in the export/share lane is automatically promoted into `ArtifactStore`.

## 1. Durable storage layout
`src/nbadb/chat/artifacts/store.py` is a very small filesystem-backed store.

### Root and bucket model
- The default root is `~/.nbadb/chat/artifacts`.
- `_bucket(name)` eagerly creates subdirectories and returns the bucket path.
- Current buckets are:
  - `templates/`
  - `findings/`

### Template writes
- `save_template(name, payload, summary)` writes `templates/{name}.json`.
- The stored JSON envelope contains `name`, `summary`, `updated_at`, and `payload`.
- The file is overwritten on repeated saves for the same name.

### Finding writes
- `save_finding(title, summary, metadata)` writes `findings/{safe_name}.json`.
- The filename is derived from `title.lower().replace(" ", "-")`.
- The stored JSON envelope contains `title`, `summary`, `updated_at`, and `metadata`.
- This slugging is intentionally minimal. It does not normalize punctuation or prevent collisions beyond exact path overwrite behavior.

## 2. Retrieval behavior

### Templates
- `load_template(name)` reads `templates/{name}.json` and returns the parsed object.
- Missing templates return `None` instead of raising.
- `list_templates()` returns sorted file stems from `templates/*.json`.

### Findings
- `search_findings(query)` is a simple substring scan over all `findings/*.json` files.
- Matching is case-insensitive.
- The haystack is only `title + summary`.
- `metadata` is returned with each hit, but it is not part of the search index.

## 3. MCP exposure
`chat/mcp_servers/artifacts.py` wraps the store with a dedicated FastMCP server named `nbadb-artifacts`.

### Tool mapping
- `save_template` parses `payload_json` and delegates to `ArtifactStore.save_template(...)`.
- `load_template` delegates to `ArtifactStore.load_template(...)` and turns misses into `{"ok": false, "error": ...}`.
- `list_templates` returns `{"items": [...]}`.
- `save_finding` parses `metadata_json`, injects `session_id`, and delegates to `ArtifactStore.save_finding(...)`.
- `search_findings` delegates to `ArtifactStore.search_findings(...)` and returns `{"items": [...]}`.

### Session scoping nuance
- The MCP process accepts a `SESSION_ID` argument.
- Templates are global within the local artifact root.
- Findings get the current `session_id` embedded in `metadata`, but retrieval is still global because search scans the whole findings bucket.
- That means session identity is preserved as payload metadata, not as a storage partition.

## 4. Runtime wiring

### MCP client path
- `chat/server/mcp_client.py` only adds `nbadb-artifacts` when `memory_mode != "off"`.
- In that mode, the main chat runtime can call the artifact MCP server over stdio.

### Copilot backend mirror
- `chat/server/copilot_backend.py` also instantiates `ArtifactStore()` directly.
- It mirrors the same save/load template and save finding behaviors as first-class backend tools.
- In practice, the persistence contract is shared across both the MCP lane and the Copilot backend lane.

## 5. Relationship to export/share flows
The export/share lane is nearby, but it is not the same storage system.

### Query-result exports are session-scoped
- In `chat/chainlit_app.py`, SQL result steps store a small payload as `cl.user_session["export_<step.id>"]`.
- Download actions rebuild a DataFrame from that payload and emit inline files.
- The payload is capped to 100 rows and disappears with session state.

### Sandbox exports are file payloads, not stored artifacts
- `chat/server/_preamble.py` helpers such as `to_csv`, `to_xlsx`, `to_json`, `to_spreadsheet`, `to_embed`, `to_social`, and `to_thread` print JSON payloads containing `export_file`, `format`, and base64 `content`.
- Chainlit decodes those payloads and attaches the resulting files inline.
- This produces downloadable artifacts for the current interaction, but it does not register them in `ArtifactStore`.

### Practical split
- Use `ArtifactStore` for reusable memory-like objects: templates and findings.
- Use export/share helpers for delivery artifacts: files, embeds, spreadsheet HTML, social cards, and threads.
- Promotion from one lane to the other would need an explicit additional step; there is no built-in bridge today.

## 6. Operational caveats
- The store is JSON-only and schema-light; no Pydantic validation happens inside `ArtifactStore` itself.
- Writes are overwrite-based and filename-derived, so repeated names or slug collisions replace prior content.
- Finding search is linear over local JSON files and only indexes title/summary text.
- `SessionArtifactRecord` and `ArtifactPointer` model richer artifact concepts elsewhere in chat, but `ArtifactStore` currently persists only templates and findings.

## Related notes
- [[wiki/topics/export-share-artifacts|Export and Share Artifact Surfaces]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| durable root path, bucket creation, template/finding envelopes, load/list/search behavior | `src/nbadb/chat/artifacts/store.py` | canonical artifact-store implementation |
| MCP server name, tool mapping, JSON argument parsing, `session_id` injection | `chat/mcp_servers/artifacts.py` | canonical MCP exposure for persistent artifacts |
| artifact server registration under `memory_mode != "off"` | `chat/server/mcp_client.py` | runtime wiring for the chat MCP client |
| Copilot backend mirror of save/load template and save finding tools | `chat/server/copilot_backend.py` | direct backend path that shares the same storage contract |
| export payload retrieval from session and expired-data behavior | `chat/chainlit_app.py` | query-result export callbacks use session state, not the artifact store |
| SQL result export payload storage, 100-row cap, action wiring | `chat/chainlit_app.py` | transient export lane in the main Chainlit renderer |
| sandbox helper inventory exposed to Python users | `chat/mcp_servers/sandbox.py` | runtime contract for export/share helpers |
| concrete export/share helper payload shapes | `chat/server/_preamble.py` | base64 file-payload emitters for CSV/XLSX/JSON/HTML/PNG/text |
| broader artifact-model vocabulary (`ArtifactKind`, `ArtifactPointer`, `ResultEnvelope`) | `src/nbadb/chat/artifacts/models.py` | useful contrast with the narrower persisted store |
| richer chat memory artifact model (`SessionArtifactRecord`) | `src/nbadb/chat/memory/models.py` | shows persistence concepts that are adjacent to, but not implemented by, `ArtifactStore` |
