# Extractor and Staging Inventory

## Purpose
Grouped internal extract for the upstream intake and `stg_*` mapping boundary.

## High-value paths
- `src/nbadb/extract/registry.py`
- `src/nbadb/extract/base.py`
- `src/nbadb/extract/stats/`
- `src/nbadb/extract/static/`
- `src/nbadb/extract/live/`
- `src/nbadb/orchestrate/staging_map.py`
- `src/nbadb/orchestrate/transformers.py`

## Notes
- `registry.py` is the extractor discovery and registration truth.
- `base.py` is the pandas-to-Polars boundary and live payload adapter.
- `staging_map.py` is the clearest endpoint-to-staging map.
- `transformers.py` is the best single place to trace transform ownership and dependencies at a high level.

## Planned wiki coverage
- `wiki/model/endpoint-coverage.md`
- `wiki/model/lineage-wayfinding.md`
- future `wiki/topics/extractor-surface.md`

## Provenance
- `src/nbadb/extract/registry.py`
- `src/nbadb/extract/base.py`
- `src/nbadb/orchestrate/staging_map.py`
- `src/nbadb/orchestrate/transformers.py`
