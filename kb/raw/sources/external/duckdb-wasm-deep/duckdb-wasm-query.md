---
title: DuckDB-Wasm Query API
kind: raw-source
status: captured
source_url: https://duckdb.org/docs/stable/clients/wasm/query
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Documents the official query execution patterns for materialized results, streaming batches, prepared statements, and file export.
---

## Source Record

- Source URL: `https://duckdb.org/docs/stable/clients/wasm/query`
- Fetch method: `webfetch` in markdown mode via DuckDB's current raw Markdown mirror after redirect
- Capture date: `2026-04-14`

## Why It Matters

This page defines how DuckDB-Wasm query work is actually executed from JavaScript: connections are explicit, queries are sequential, and callers choose between full Arrow materialization and streamed result batches. It also covers prepared statements and client-side Parquet export.

## Key Excerpts

> "DuckDB-Wasm provides functions for querying data. Queries are run sequentially."

> "First, a connection needs to be created by calling connect. Then, queries can be run by calling query or send."

> "Prepare query ... and run the query with materialized results ... or result chunks."

> "COPY (SELECT * FROM tbl) TO 'result-snappy.parquet' (FORMAT parquet);"

## Capture Notes

- `query` is the materialized-result path, while `send` exposes lazy batch iteration.
- Prepared statements preserve the same split between eager and streamed execution.
- The examples keep connection and statement cleanup explicit, reinforcing that browser memory release is a caller concern.
- Export uses SQL `COPY` plus `copyFileToBuffer`, so downloaded artifacts still flow through the registered DuckDB file layer.
