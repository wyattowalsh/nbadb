---
title: DuckDB, Polars, and Pandera in nbadb
tags:
  - kb
  - tooling
  - duckdb
  - polars
  - pandera
aliases:
  - Data Stack
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# DuckDB, Polars, and Pandera in nbadb

## Why this stack exists
`nbadb` is built around a warehouse-first ELT flow:
1. extract upstream NBA payloads into Python
2. normalize them into `polars.DataFrame` objects
3. persist staging data into DuckDB
4. run SQL-first transforms for the star/analytics surface
5. validate contracts at raw, staging, and star layers with Pandera

## Repo-specific usage
- `pyproject.toml` pins `duckdb`, `polars`, and `pandera[polars]`
- `README.md` describes DuckDB staging plus SQL-first transforms and 3-tier Pandera validation
- `src/nbadb/orchestrate/orchestrator.py` converts extracted frames to `LazyFrame` before transform execution
- `src/nbadb/core/db.py` opens the persistent DuckDB database and creates pipeline state tables there
- `src/nbadb/schemas/base.py` defines the base Pandera behavior used across the repo

## Maintainer rules
- keep dataframe work in Polars at the Python boundary
- prefer lazy once data leaves extraction
- treat DuckDB as the warehouse execution layer
- treat Pandera classes as contracts, not decoration
- remember that schema metadata also feeds generated docs and lineage

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| dependency floor | `pyproject.toml` | package dependency truth |
| architecture summary | `README.md` | public data stack framing |
| orchestrator lazy-frame behavior | `src/nbadb/orchestrate/orchestrator.py` | pipeline flow |
| DuckDB manager role | `src/nbadb/core/db.py` | persistence and state tables |
| Pandera base behavior | `src/nbadb/schemas/base.py` | schema defaults |
| docs-generation dependency on schema metadata | `src/nbadb/docs_gen/data_dictionary.py` | generated docs |
| ER generation dependency on schema metadata | `src/nbadb/docs_gen/er_diagram.py` | generated diagram |
| lineage generation dependency on schema metadata | `src/nbadb/docs_gen/lineage.py` | generated lineage |
