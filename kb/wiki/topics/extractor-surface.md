---
title: Extractor Surface
tags:
  - kb
  - topics
  - extract
  - staging
aliases:
  - Extractor Surface Map
kind: concept
status: active
updated: 2026-04-14
source_count: 6
---

# Extractor Surface

This is a companion note to the canonical code. It summarizes how the extractor surface is assembled today, what work the shared base class performs at the boundary, and why the staging surface is materially larger than the registry count.

## Current surface snapshot
The extractor registry is discovery-based, not hand-enumerated. `EndpointRegistry.discover()` imports modules under:
- `nbadb.extract.stats`
- `nbadb.extract.static`
- `nbadb.extract.live`

At current runtime, discovery yields `151` registered extractor classes.

The staging surface is larger because one extractor can fan out into multiple result sets and multiple staging targets. The current `STAGING_MAP` contains `402` staging entries.

## Boundary contract in `BaseExtractor`
`BaseExtractor` centralizes the extraction boundary so individual extractors stay thin.

Shared behaviors:
- injects request timeout from per-endpoint override first, then settings
- calls `nba_api` and converts pandas payloads to Polars
- normalizes all column names to `snake_case` at the boundary
- injects `season_type` into result sets when the request used a season-type kwarg and the payload omitted the column
- falls back when mixed pandas object columns break Arrow conversion
- provides separate helpers for single-result, multi-result, live single-payload, and live multi-payload endpoints

## How registry surface turns into staging surface
`StagingEntry` is the bridge between extractor names and orchestrated staging loads.

Important fields:
| Field | Meaning |
| --- | --- |
| `endpoint_name` | Registry key or extractor name |
| `staging_key` | Concrete `stg_*` target |
| `param_pattern` | Which orchestrator parameterization strategy to use |
| `result_set_index` | Which result set to select from multi-result endpoints |
| `use_multi` | Whether to use the multi-result extraction path |
| `min_season` | Earliest supported season year |

## KB takeaways
- Treat the registry count as the extractor surface.
- Treat the staging map count as the operational ingest surface.
- When tracing lineage, check both the extractor class and the relevant `StagingEntry`.
- If a source appears missing, confirm both discovery and staging coverage; registry presence alone does not guarantee a staged table.

## Related notes
- [[wiki/model/endpoint-coverage|Endpoint Coverage]]
- [[wiki/model/lineage-wayfinding|Lineage Wayfinding]]
- [[wiki/topics/nba-api-source-summary|NBA API Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| registry structure and discovery | `src/nbadb/extract/registry.py` | extractor discovery and count |
| shared extraction boundary | `src/nbadb/extract/base.py` | timeout, pandas-to-Polars, normalization |
| staging-entry semantics | `src/nbadb/orchestrate/staging_map.py` | endpoint-to-staging bridge |
| current staging surface framing | `raw/extracts/internal/extractor-and-staging-inventory.md` | KB internal extract |
| upstream endpoint context | `raw/sources/external/upstream-nba/` | external contract capture |
| repo maintainer framing | `AGENTS.md` | extract and transform module map |
