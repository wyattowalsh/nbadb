---
title: "Polars Joins Guide"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - polars
  - joins
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://docs.pola.rs/user-guide/transformations/joins/
capture_type: markdown-extract
---

# Polars Joins Guide

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://docs.pola.rs/user-guide/transformations/joins/` |
| Owner | Polars project |
| Scope | User-guide reference for equi joins, join strategies, non-equi joins, asof joins, and cross joins |
| Why it matters to nbadb | `nbadb` performs many join-heavy Polars transformations before and around DuckDB-backed warehouse execution |

## Summary
This guide is Polars' main overview of join behavior. It covers standard equi joins, strategy-specific row retention, computed key expressions, non-equi joins with predicates, asof joins for nearest-key matching, and Cartesian products.

## Key Points
- `join` supports `inner`, `left`, `right`, `full`, `semi`, `anti`, and `cross` strategies.
- Join keys can be expressions, not just shared column names, which allows normalization during the join itself.
- Full joins may keep both key columns unless `coalesce=True` is used.
- `join_where` handles non-equi joins by predicate rather than equality.
- `join_asof` matches on nearest key and can be constrained with `by=` and `tolerance=`.
- The guide treats semi and anti joins as row-filtering tools, not full column-merging operations.

## nbadb Relevance
- Useful when deciding whether a data-shaping step belongs in Polars or in DuckDB SQL.
- Dynamic-key joins are relevant for upstream normalization before warehouse load.
- Semi/anti join semantics map cleanly to existence and exclusion filters used in pipeline logic.
- Asof joins matter for time-aligned event data and could inform future live or tracking datasets.

## Notable Sections
- Quick reference table
- Equi joins
- Join strategies
- Non-equi joins
- Asof join
- Cartesian product

## Provenance
- Fetched from `https://docs.pola.rs/user-guide/transformations/joins/` on `2026-04-14`
