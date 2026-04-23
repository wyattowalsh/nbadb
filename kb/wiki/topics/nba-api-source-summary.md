---
title: NBA API Source Summary
tags:
  - kb
  - source
  - upstream
aliases: []
kind: source-summary
status: active
updated: 2026-04-22
source_count: 5
---

# NBA API Source Summary

## Source record
| Field | Value |
|-------|-------|
| Source ID | `nba-api` |
| Raw source | `pyproject.toml`; `AGENTS.md`; `src/nbadb/extract/base.py`; `src/nbadb/extract/registry.py`; `raw/sources/external/upstream-nba/` |
| Capture or extract | `raw/extracts/internal/extractor-and-staging-inventory.md` plus upstream capture notes |
| Status | seeded |

## Summary
This source set establishes the `nba_api` dependency and the extraction boundary around it: nbadb discovers extractors from `stats`, `static`, and `live` packages, then normalizes upstream pandas payloads into Polars frames with snake_case columns, timeout injection, and optional `season_type` augmentation.

## Planned wiki coverage
- `wiki/model/endpoint-coverage.md`
- `wiki/topics/upstream-nba-api.md`
- `wiki/topics/extraction-boundary.md`

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Declared `nba_api` dependency | `pyproject.toml` | Confirms dependency floor |
| Count claim and runtime-surface framing | `AGENTS.md` | Current repo-level summary |
| Extractor package split | `src/nbadb/extract/registry.py` | Shows registration and discovery |
| Pandas-to-Polars boundary | `src/nbadb/extract/base.py` | Shows normalization path |
| Grouped upstream/extractor bridge | `raw/extracts/internal/extractor-and-staging-inventory.md`; `raw/sources/external/upstream-nba/` | Current source bridge into maintained notes |
