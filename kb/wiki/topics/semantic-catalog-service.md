---
title: Semantic Catalog Service
tags:
  - kb
  - topics
  - chat
  - catalog
  - semantic
  - mcp
aliases:
  - Chat Semantic Catalog Service
  - Semantic Warehouse Catalog
  - Catalog Search and Recommendation Service
kind: concept
status: active
updated: 2026-04-15
source_count: 8
---

# Semantic Catalog Service

Use this note for the shortest grounded answer to "what does `src/nbadb/chat/catalog/service.py` infer and how does that semantic catalog reach MCP and Copilot tools?"

## Purpose
`src/nbadb/chat/catalog/service.py` is the semantic discovery layer over the DuckDB warehouse.

It does four jobs:
- inspects DuckDB `information_schema` and turns tables into `CatalogObject` records
- assigns each object to a family and access tier
- infers grain, entities, join keys, measures, time dimensions, and aliases from table names plus columns
- ranks objects for search and recommendation flows used before SQL drafting

There is no cache in this module. `list`, `search`, and `recommend` rebuild catalog objects directly from live DuckDB metadata on each request.

## Model Shape
`src/nbadb/chat/catalog/models.py` defines three core models:
- `CatalogObjectFamily`: `analytics`, `agg`, `dimension`, `fact`, `bridge`, `internal`
- `AccessTier`: `semantic-preferred`, `raw-allowed`, `internal-restricted`
- `CatalogObject`: the semantic record returned by catalog search and inspection

`CatalogObject` carries:
- identity: `name`, `family`, `access_tier`, `description`, `grain`
- schema hints: `columns`, `join_keys`, `time_dimensions`
- semantic hints: `primary_entities`, `measures`, `aliases`
- guidance: `recommended_usage`, `common_pitfalls`, `example_questions`

## Family And Access-Tier Taxonomy
Family comes entirely from the table-name prefix via `table_family(...)`:

| Prefix or case | Family | Access tier |
| --- | --- | --- |
| `analytics_` | `analytics` | `semantic-preferred` |
| `agg_` | `agg` | `semantic-preferred` |
| `dim_` | `dimension` | `semantic-preferred` |
| `fact_` | `fact` | `raw-allowed` |
| `bridge_` | `bridge` | `raw-allowed` |
| anything else | `internal` | `internal-restricted` |

The policy intent is simple:
- `analytics`, `agg`, and `dimension` are the preferred semantic surfaces for normal analysis
- `fact` and `bridge` are allowed when the user needs raw event detail and can manage join cardinality
- `internal` is discoverable in the base catalog model but penalized in ranking and filtered out of recommendations

## Grain, Entity, And Join-Key Inference
The service does not read hand-authored metadata. It infers semantic hints from the table name and column list.

### Grain
`_infer_grain(...)` strips one leading family prefix and replaces underscores with spaces.

Examples:
- `fact_player_game_traditional` -> `player game traditional`
- `dim_team` -> `team`
- `analytics_player_scoring_trends` -> `player scoring trends`

### Primary entities
`_infer_entities(...)` tokenizes the table name and columns, then matches a fixed entity vocabulary:
- `player`, `team`, `game`, `season`, `lineup`, `shot`, `play`, `draft`, `coach`, `arena`

It keeps the first four matched entities.

### Join keys
`_infer_join_keys(...)` keeps up to six columns that either:
- match known stable keys such as `player_id`, `team_id`, `game_id`, `season`, `season_id`, `lineup_id`
- or end in `_id`

This means the catalog's join advice is heuristic but usually useful for planning and validator checks.

### Measures and time dimensions
`_infer_measures(...)` skips IDs and time tokens, then matches a small synonym map for common stats such as points, rebounds, assists, steals, blocks, turnovers, and minutes.

`_infer_time_dimensions(...)` keeps columns whose names include tokens like `season`, `date`, `time`, `year`, `month`, `week`, or `day`.

## Aliases And Guidance Text
Aliases are generated, not curated.

`_build_aliases(...)` starts from:
- the table name with spaces
- the inferred grain
- `"<family> <grain>"`

Then it adds:
- `"<entity> <family>"`
- `"<entity> <grain>"`
- `"<measure> <grain>"`

This makes objects discoverable by a mix of warehouse naming, grain phrasing, entity phrasing, and stat phrasing.

The service also synthesizes:
- `description`
- `recommended_usage`
- `common_pitfalls`
- `example_questions`

Those fields are later tokenized and contribute to ranking.

## Search Behavior
`search_catalog(...)` returns ranked `CatalogObject` matches for a free-text query.

Search flow:
1. blank queries return `[]`
2. all catalog objects are rebuilt from DuckDB metadata
3. query tokens are expanded through the measure alias map, so `pts` also activates `point` and `points`
4. every object is scored against name, aliases, grain, entities, columns, measures, description, and family terms
5. only positive-score results survive, ordered by score descending and then by table name

Important ranking behavior:
- exact table-name match gets the largest boost
- alias exact/substring matches get strong boosts
- full token coverage gets an extra bonus
- `semantic-preferred` objects get a ranking bonus
- `raw-allowed` objects get a smaller bonus
- `internal-restricted` objects get a penalty

In practice, this makes semantic surfaces rise above equally token-compatible internal or raw surfaces.

## Recommendation Behavior
`recommend_surfaces(entity, grain)` is a narrower planner helper than free-text search.

Behavior:
- builds one query string from `entity` plus optional `grain`
- ranks up to 24 candidates through the same search scorer
- drops any `internal-restricted` objects
- returns up to 12 remaining objects

So recommendation is just search with a planner-shaped input and a stricter post-filter.

## MCP And Copilot Surfaces
### MCP surface
`chat/mcp_servers/catalog.py` wraps the service as FastMCP server `nbadb-catalog` with three tools:
- `search_catalog`
- `get_object`
- `recommend_surfaces`

`chat/server/mcp_client.py` always wires `nbadb-catalog` into the deepagents runtime alongside SQL, SQL validator, and sandbox servers.

### Copilot surface
`chat/server/copilot_backend.py` does not use MCP subprocesses. Instead it mirrors the same semantic catalog capability in-process with Copilot tools:
- `search_catalog_tool`
- `get_object`
- `recommend_surfaces_tool`

Those tools call the same `nbadb.chat.catalog` functions and are explicitly whitelisted in the Copilot permission handler.

### Capability manifest
`src/nbadb/chat/runtime/capabilities.py` advertises `semantic_catalog: true` in `CapabilityManifest`.

Treat that as descriptive capability metadata, not proof that every runtime exposes the exact same tool list. The deepagents MCP path and Copilot path overlap, but they are assembled differently.

## Practical Mental Model
- family/access tier decides whether a surface is preferred, raw-but-allowed, or restricted
- grain/entities/join keys are inferred heuristically from warehouse naming and schema shape
- aliases make stat and entity phrasing searchable without a manually curated catalog
- search is a weighted semantic matcher
- recommendations are search results filtered for planning-safe surfaces
- MCP and Copilot both expose the catalog, but one does it over FastMCP and the other does it with in-process Copilot tools

## Related notes
- [[wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[wiki/topics/sql-validator-service|SQL Validator Service]]
- [[wiki/topics/query-safety|Query Safety]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| catalog model types and `CatalogObject` fields | `src/nbadb/chat/catalog/models.py` | defines `CatalogObjectFamily`, `AccessTier`, and `CatalogObject` |
| exported public catalog service API | `src/nbadb/chat/catalog/__init__.py` | re-exports `table_family`, `access_tier_for_family`, `build_catalog_object`, `list_catalog_objects`, `get_catalog_object`, `search_catalog`, and `recommend_surfaces` |
| live DuckDB introspection, family/access-tier rules, grain/entity/join-key inference, aliases, descriptions, guidance, search scoring, and recommendation filtering | `src/nbadb/chat/catalog/service.py` | canonical implementation of semantic catalog behavior |
| semantic discovery server name and MCP tool surface | `chat/mcp_servers/catalog.py` | FastMCP server `nbadb-catalog` with `search_catalog`, `get_object`, and `recommend_surfaces` |
| deepagents MCP wiring and always-on inclusion of the catalog server | `chat/server/mcp_client.py` | `nbadb-catalog` is part of the core built-in server bundle |
| Copilot in-process catalog tools and permission allowlist | `chat/server/copilot_backend.py` | mirrors catalog behavior with `@define_tool` functions instead of MCP subprocesses |
| advertised runtime capability flag | `src/nbadb/chat/runtime/capabilities.py` | `CapabilityManifest` includes `semantic_catalog: bool = True` |
| no-cache behavior and service-layer summary | `kb/raw/extracts/internal/chat-service-layer-inventory.md`; `kb/raw/extracts/internal/mcp-server-inventory.md` | internal extracts summarize service role, no-cache behavior, and runtime split |
