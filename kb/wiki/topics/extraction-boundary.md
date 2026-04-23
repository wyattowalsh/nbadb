---
title: Extraction Boundary
tags:
  - kb
  - topics
  - extract
  - staging
aliases:
  - Upstream Extraction Boundary
kind: concept
status: active
updated: 2026-04-22
source_count: 5
---

# Extraction Boundary

Use this note for the exact handoff from upstream endpoint calls into nbadb-owned extraction and staging semantics.

## Boundary summary
The extraction boundary is where nbadb stops trusting upstream payload shape as-is and starts enforcing repo-owned conventions.

That boundary spans three linked seams:
1. `src/nbadb/extract/registry.py` discovers and registers extractor classes.
2. `src/nbadb/extract/base.py` converts upstream payloads into normalized Polars frames.
3. `src/nbadb/orchestrate/staging_map.py` declares how endpoint outputs map onto `stg_*` tables and season-type capability patterns.

## What changes at this boundary
### Extractor discovery
Registry discovery is package-driven rather than hard-coded by one flat endpoint list. The extractor layer is split into `stats`, `static`, and `live`, which is why the upstream family split matters operationally.

### Frame normalization
`BaseExtractor` is the canonical pandas-to-Polars handoff. It:
- injects timeout overrides into upstream calls
- lowercases or snake-cases column names
- preserves `season_type` when the upstream call carried that semantic
- converts live payloads into structured frames plus `payload_json`

### Staging contract
`staging_map.py` is where upstream endpoints become warehouse staging semantics.

That layer adds:
- stable `stg_*` ownership
- parameter-pattern classification such as `season`, `game`, `live`, `player`, and `team`
- season-type capability inference
- minimum-season and deprecation cutoffs where applicable

So "the extractor works" and "the endpoint is part of the strict warehouse contract" are not the same statement.

## Practical maintainer rule
- Use [[wiki/topics/upstream-nba-api|Upstream NBA API]] when the question is about upstream families or source dependency.
- Use this note when the question is about normalization, staging ownership, or where strict support semantics begin.
- Use [[wiki/topics/strict-source-complete-roadmap|Strict Source-Complete Roadmap]] when the question is about remaining modeled or contract gaps after this boundary.

## Related notes
- [[wiki/topics/upstream-nba-api|Upstream NBA API]]
- [[wiki/topics/extractor-surface|Extractor Surface]]
- [[wiki/model/endpoint-coverage|Endpoint Coverage]]
- [[wiki/topics/strict-source-complete-roadmap|Strict Source-Complete Roadmap]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| extractor discovery and package-family registration | `src/nbadb/extract/registry.py` | canonical registry boundary |
| upstream call normalization, timeout injection, snake_case conversion, and live payload shaping | `src/nbadb/extract/base.py` | canonical extraction boundary |
| endpoint-to-staging ownership and season-type capability semantics | `src/nbadb/orchestrate/staging_map.py` | canonical staging contract |
| grouped extractor/staging bridge | `raw/extracts/internal/extractor-and-staging-inventory.md` | current internal inventory |
| repo-level extractor/staging framing | `AGENTS.md` | maintainer-facing contract summary |
