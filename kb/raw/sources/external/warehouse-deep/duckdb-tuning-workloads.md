---
title: "DuckDB Tuning Workloads"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - duckdb
  - performance
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads.html
capture_type: markdown-extract
---

# DuckDB Tuning Workloads

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads.html` |
| Owner | DuckDB Foundation |
| Scope | Performance guide for memory, threading, spill behavior, profiling, remote IO, and connection reuse |
| Why it matters to nbadb | `nbadb` runs long warehouse rebuilds, large joins, and file-backed scans where DuckDB tuning can materially change stability and runtime |

## Summary
This guide documents the main operational knobs for DuckDB performance. It covers when to disable insertion-order preservation, how row groups drive parallelism, how larger-than-memory workloads spill to disk, what kinds of operators are most memory-intensive, and how to reason about remote-file IO and connection reuse.

## Key Points
- `SET preserve_insertion_order = false;` can reduce memory pressure during large CSV or Parquet import/export work.
- Parallelism is bounded by row groups; the default DuckDB row-group size is `122,880` rows.
- DuckDB can spill larger-than-memory work to a temp directory, configurable via `temp_directory`.
- Blocking operators called out as memory-heavy are `GROUP BY`, `JOIN`, `ORDER BY`, and window functions.
- Prepared statements mainly help with many repeated sub-100ms queries, not big warehouse scans.
- Remote-file reads use synchronous IO, so more threads can help hide request latency.
- Reusing connections preserves caches and reduces overhead; compressed persistent tables can outperform uncompressed in-memory tables.

## nbadb Relevance
- Directly relevant to full historical rebuilds, star-schema transforms, and export phases.
- Useful source for tuning thread count and spill directory choices in constrained environments.
- The blocking-operator list maps closely to the project's heavy transform shapes.
- The remote IO guidance matters when scanning network-backed Parquet or object-store inputs.

## Notable Sections
- `preserve_insertion_order`
- Parallelism and row groups
- Larger-than-memory workloads
- Profiling
- Querying remote files
- Best practices for using connections
- Persistent vs. in-memory tables

## Provenance
- Fetched from `https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads.html` on `2026-04-14`
