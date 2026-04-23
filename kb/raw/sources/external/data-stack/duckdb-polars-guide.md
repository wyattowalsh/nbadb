---
title: "DuckDB Polars Integration Guide"
tags:
  - kb
  - raw
  - source
  - external
  - data-stack
  - duckdb
  - polars
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/docs/current/guides/python/polars.html
capture_type: markdown-extract
---

# DuckDB Polars Integration Guide

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/docs/current/guides/python/polars.html` |
| Owner | DuckDB Foundation |
| Scope | Python guide for reading Polars frames in DuckDB and returning query results back to Polars |
| Why it matters to nbadb | `nbadb` moves data between Polars and DuckDB throughout extraction, staging, and transform work |

## Summary
This guide describes DuckDB's Arrow-backed bridge to Polars. DuckDB can query a Polars `DataFrame` directly by variable name and can emit results back as either a Polars `DataFrame` or `LazyFrame` via `.pl()` and `.pl(lazy=True)`.

## Key Points
- Requires `pyarrow` for the DuckDB-Polars bridge.
- DuckDB can scan in-memory Polars objects without manual serialization.
- Query results can be materialized eagerly or returned as a Polars lazy plan.
- The integration is framed as efficient because it relies on Arrow interchange.

## nbadb Relevance
- Confirms that in-memory Polars to DuckDB interchange is an intended, documented workflow.
- Supports the project pattern of doing Python-boundary dataframe work in Polars while keeping SQL execution in DuckDB.
- Useful source when reasoning about zero-copy or low-copy handoffs during orchestration and export.

## Notable Sections
- Installation
- Polars to DuckDB
- DuckDB to Polars
- LazyFrame result conversion

## Provenance
- Fetched from `https://duckdb.org/docs/current/guides/python/polars.html` on `2026-04-14`
