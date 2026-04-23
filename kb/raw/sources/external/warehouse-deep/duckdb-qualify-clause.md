---
title: "DuckDB QUALIFY Clause"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - duckdb
  - sql
  - window-functions
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/docs/current/sql/query_syntax/qualify.html
capture_type: markdown-extract
---

# DuckDB QUALIFY Clause

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/docs/current/sql/query_syntax/qualify.html` |
| Owner | DuckDB Foundation |
| Scope | Dedicated syntax reference for filtering window-function results with `QUALIFY` |
| Why it matters to nbadb | Warehouse analytics often need rank- or window-based filtering without wrapping subqueries |

## Summary
DuckDB uses `QUALIFY` to filter the results of window functions in the same way `HAVING` filters aggregates. The clause exists to avoid extra `WITH` or subquery layers when keeping only selected ranked or windowed rows.

## Key Points
- `QUALIFY` filters based on window-function output, not just on whether a `WINDOW` clause is present.
- It appears after the optional `WINDOW` clause and before `ORDER BY`.
- The filter can repeat a window function inline or reference an alias computed in the `SELECT` list.
- The docs show equivalent `QUALIFY` and `WITH`-based rewrites, making the tradeoff explicit.

## nbadb Relevance
- Useful for top-N-per-group or ranked dedup patterns in facts, aggregates, and analytics views.
- Lets warehouse SQL stay flatter and more readable than nested CTE-based window filters.
- Important upstream reference when deciding whether a rank filter belongs in `QUALIFY` rather than `WHERE` or an outer query.

## Notable Sections
- Direct `QUALIFY` examples
- Alias-based `QUALIFY` usage
- `WINDOW` plus `QUALIFY`
- Equivalent `WITH` clause rewrite

## Provenance
- Fetched from `https://duckdb.org/docs/current/sql/query_syntax/qualify.html` on `2026-04-14`
