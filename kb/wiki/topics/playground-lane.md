---
title: Playground Lane
tags:
  - kb
  - topics
  - docs
  - playground
  - duckdb
aliases:
  - SQL Playground Lane
  - Browser Query Rehearsal Lane
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Playground Lane

Use this note when the question is "Can I rehearse the SQL shape in-browser first?" rather than "How do I query the real warehouse?"

## What this lane is
The docs playground is the no-install warm-up lane for `nbadb` SQL work. It is positioned as a browser-first place to practice joins, CTEs, aggregates, window functions, and chartable result shapes before touching a local `nba.duckdb` file.

## User contract
- runs in the browser tab, not against the local warehouse by default
- safe for disposable query rehearsal
- explicitly hands users off to the real-data lanes once the query shape is correct
- framed for onboarding, teaching DuckDB syntax, and sanity-checking query structure

## Runtime mechanics
- `docs/lib/duckdb.ts` owns a shared DuckDB-WASM singleton
- the engine is lazy-loaded on first use
- queries run through `runQuery()` and return plain-object rows plus column names
- if a query times out, the docs app destroys the entire in-browser DuckDB session and surfaces a reset error
- remote Parquet registration is explicit and guarded by table-name validation

## Practical boundaries
- this lane does not auto-mount the user's local `nbadb` warehouse
- it is best for SQL structure, not full-dataset confidence
- the handoff is intentional: move to local DuckDB, Parquet usage, or schema pages once the query shape is locked in

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-generator-internals|Docs Generator Internals]]
- [[wiki/topics/query-patterns|Query Patterns]]

## Provenance
| Claim or section | Repo or raw source | Notes |
|------------------|--------------------|-------|
| browser-first warm-up lane and next-step guidance | `docs/content/docs/playground.mdx` | canonical user-facing contract |
| shared DuckDB singleton and timeout reset | `docs/lib/duckdb.ts` | implementation mechanics |
| docs stack and `SqlPlayground` contract | `docs/AGENTS.md` | docs-app operating contract |
| current dependency versions | `docs/package.json` | package truth for docs app |
| upstream browser DuckDB capabilities | `raw/sources/external/docs-app-stack/duckdb-wasm.md` | browser execution model |
| upstream framework/runtime context | `raw/sources/external/docs-app-stack/nextjs-docs.md` | app runtime context |
| upstream typed content-processing model | `raw/sources/external/docs-app-stack/fumadocs-mdx.md` | MDX/content layer context |
| internal docs app inventory | `raw/extracts/internal/docs-app-stack-inventory.md` | repo-local stack inventory |
