---
title: "Polars Lazy API Concept Guide"
tags:
  - kb
  - raw
  - source
  - external
  - data-stack
  - polars
  - lazy
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://docs.pola.rs/user-guide/concepts/lazy-api/
capture_type: markdown-extract
---

# Polars Lazy API Concept Guide

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://docs.pola.rs/user-guide/concepts/lazy-api/` |
| Owner | Polars project |
| Scope | Conceptual explanation of eager vs lazy execution, optimizer behavior, and query-plan inspection |
| Why it matters to nbadb | `nbadb` explicitly prefers lazy Polars once data leaves extraction |

## Summary
This guide explains that Polars lazy queries defer execution until `.collect()`, which allows the planner to optimize the whole pipeline. The documented benefits include predicate pushdown, projection pushdown, lower memory use, and better CPU efficiency.

## Key Points
- Lazy mode is preferred in most cases because it gives the optimizer the full query graph.
- `scan_*` APIs are the lazy counterparts to eager `read_*` APIs.
- `collect()` is the explicit execution boundary.
- `explain()` shows the optimized logical plan and makes pushdown visible.

## nbadb Relevance
- Strong external support for the repo rule to prefer lazy Polars in orchestration and transform-adjacent code.
- Useful reference for code review when deciding whether an eager dataframe step should stay eager.
- Helps explain why schema contracts and selected-column discipline reduce IO and memory pressure in long rebuilds.

## Notable Sections
- When to use lazy vs eager
- Predicate pushdown
- Projection pushdown
- Query-plan preview with `explain()`

## Provenance
- Fetched from `https://docs.pola.rs/user-guide/concepts/lazy-api/` on `2026-04-14`
