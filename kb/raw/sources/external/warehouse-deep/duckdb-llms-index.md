---
title: "DuckDB llms.txt Index"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - duckdb
  - llms
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://duckdb.org/llms.txt
capture_type: markdown-extract
---

# DuckDB llms.txt Index

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://duckdb.org/llms.txt` |
| Owner | DuckDB Foundation |
| Scope | LLM-oriented top-level guidance for DuckDB capabilities, usage cautions, and docs entrypoints |
| Why it matters to nbadb | `nbadb` relies on DuckDB as its warehouse and staging engine, so this page is a concise upstream model of supported patterns |

## Summary
DuckDB's `llms.txt` is a compact orientation page for AI and humans. It frames DuckDB as an in-process analytical database, highlights the PostgreSQL-like SQL surface, points to major client docs, and calls out operational guidance like file-format support, in-memory mode, insertion-order tuning, and lakehouse extensions.

## Key Points
- DuckDB presents one SQL surface across clients, with PostgreSQL-compatible syntax.
- It can query CSV, JSON, and Parquet directly, which aligns with file-backed warehouse workflows.
- The page explicitly recommends `SET preserve_insertion_order = false;` for large loads to reduce memory pressure.
- It points to client docs, extension docs, and example projects rather than trying to be exhaustive itself.
- DuckLake is called out for workloads that need concurrent write access across multiple clients.

## nbadb Relevance
- Good high-signal upstream summary for agent context when reasoning about DuckDB behavior.
- Reinforces documented support for direct file querying and mixed in-memory/persistent usage.
- Highlights the exact insertion-order knob that matters for large rebuild and export workloads.

## Notable Sections
- Things to remember when using DuckDB
- Clients overview
- Extensions overview
- Example integrations and projects

## Provenance
- Fetched from `https://duckdb.org/llms.txt` on `2026-04-14`
