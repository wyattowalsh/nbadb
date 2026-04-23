---
title: "DuckDB Documentation Index"
tags:
  - kb
  - raw
  - source
  - external
  - data-stack
  - duckdb
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/docs/current/index
capture_type: markdown-extract
---

# DuckDB Documentation Index

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/docs/current/index` |
| Owner | DuckDB Foundation |
| Scope | Primary docs entrypoint for DuckDB SQL, Python client, guides, extensions, operations, and internals |
| Why it matters to nbadb | `nbadb` uses DuckDB as the staging and warehouse execution layer |

## Summary
The DuckDB docs index is the top-level map for the whole product surface. It points to the SQL reference, Python client APIs, import/export guides, performance guidance, extension docs, operations manual, and internals pages.

## Key Points
- DuckDB documentation is organized around connection model, client APIs, SQL, data import/export, extensions, performance, and internals.
- The Python client and guides are first-class parts of the docs surface, which matters for `nbadb`'s Python-driven orchestration.
- The docs expose both user-facing warehouse behavior and lower-level operational details like storage footprint, limits, and non-deterministic behavior.

## nbadb Relevance
- Anchor source for DuckDB SQL semantics used by `SqlTransformer`-based transforms.
- Reference hub for file-format support behind exports and staging reads, especially CSV, JSON, and Parquet.
- Navigation root for performance and operations pages relevant to large historical rebuilds and resumable runs.

## Notable Sections
- Connect overview
- Python client docs
- SQL introduction and statements
- Data import/export
- Performance guides
- Operations manual
- Internals overview

## Provenance
- Fetched from `https://duckdb.org/docs/current/index` on `2026-04-14`
