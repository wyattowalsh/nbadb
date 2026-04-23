---
title: "DuckDB SELECT Statement"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - duckdb
  - sql
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/docs/current/sql/statements/select.html
capture_type: markdown-extract
---

# DuckDB SELECT Statement

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/docs/current/sql/statements/select.html` |
| Owner | DuckDB Foundation |
| Scope | Canonical DuckDB reference page for `SELECT` statement clause order and semantics |
| Why it matters to nbadb | Most warehouse transforms in `nbadb` compile to DuckDB `SELECT` queries via SQL transformers |

## Summary
This page defines the canonical DuckDB `SELECT` statement layout and explains the logical role of each clause. It covers clause order, sampling, grouping, windowing, `QUALIFY`, ordering, `VALUES`, and the `rowid` pseudocolumn.

## Key Points
- Canonical order is `SELECT ... FROM ... USING SAMPLE ... WHERE ... GROUP BY ... HAVING ... WINDOW ... QUALIFY ... ORDER BY ... LIMIT`.
- The `SELECT` list appears first syntactically but is described as logically executed at the end.
- `SAMPLE` is applied after `FROM` sources and joins, before filtering and aggregation.
- `QUALIFY` is part of the normal `SELECT` grammar and filters window-function results.
- DuckDB exposes a `rowid` pseudocolumn that is stable within a transaction, but the docs strongly advise against using it as an identifier.

## nbadb Relevance
- Useful anchor for clause-order correctness in `SqlTransformer` SQL.
- Confirms where `WINDOW` and `QUALIFY` sit in DuckDB's grammar, which matters for analytic fact and derived queries.
- The `rowid` note is important when evaluating shortcut query patterns that should not leak into durable warehouse keys.

## Notable Sections
- Examples
- Syntax and canonical clause order
- Clause-by-clause semantics
- Row IDs
- Full syntax diagram

## Provenance
- Fetched from `https://duckdb.org/docs/current/sql/statements/select.html` on `2026-04-14`
