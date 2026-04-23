---
title: Upstream NBA API
tags:
  - kb
  - topics
  - upstream
  - api
aliases:
  - nba_api Runtime Surface
kind: concept
status: active
updated: 2026-04-22
source_count: 5
---

# Upstream NBA API

Use this note when the question is "what exactly is nbadb upstream of?" rather than "how is a specific endpoint modeled downstream?"

## Core boundary
nbadb is built around the current `nba_api` runtime surface plus a small live-JSON lane for active-game snapshots.

The current upstream split is:
- `nba_api.stats` style endpoints for the bulk historical and statistical surface
- `nba_api.live` style payloads for active-game and live-snapshot surfaces
- `nba_api.static` style surfaces for players, teams, arenas, awards, and other reference data

`src/nbadb/extract/registry.py` discovers extractors from those three package families. nbadb does not treat the upstream package as a monolith; it explicitly mirrors the stats/static/live split in its own extractor layer.

## What nbadb takes from upstream
- endpoint response payloads and parameter contracts
- season-type semantics where the upstream endpoint supports them
- live payload structures that need snapshot-style handling
- reference-data surfaces such as teams, players, and awards

## What nbadb does not preserve unchanged
nbadb is not a raw mirror of upstream pandas frames.

At the extraction boundary it already:
- converts upstream pandas frames into Polars
- renames columns to snake_case
- injects `season_type` where the upstream call carried it but the frame omitted it
- serializes live payload records with `payload_json` for snapshot/replayability

So the upstream API is the source contract, but not the final user-facing schema.

## Practical maintainer rule
- Use this note when you need the upstream family split, dependency boundary, or normalization handoff.
- Use [[wiki/model/endpoint-coverage|Endpoint Coverage]] when you need modeled-vs-excluded-vs-gap interpretation.
- Use [[wiki/topics/extraction-boundary|Extraction Boundary]] when you need the exact handoff from upstream payloads into nbadb extraction and staging semantics.

## Related notes
- [[wiki/model/endpoint-coverage|Endpoint Coverage]]
- [[wiki/topics/extractor-surface|Extractor Surface]]
- [[wiki/topics/extraction-boundary|Extraction Boundary]]
- [[wiki/topics/nba-api-source-summary|NBA API Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| repo-level dependency and runtime-surface framing | `AGENTS.md`; `pyproject.toml` | current dependency and project framing |
| extractor discovery across stats/static/live packages | `src/nbadb/extract/registry.py` | canonical extractor-family split |
| normalization from upstream pandas payloads into snake_case Polars frames | `src/nbadb/extract/base.py` | extraction-time normalization contract |
| grouped extractor and staging bridge | `raw/extracts/internal/extractor-and-staging-inventory.md` | current internal extract |
| upstream capture set for `nba_api` and live JSON docs | `raw/sources/external/upstream-nba/` | external evidence layer |
