---
title: DuckDB-Wasm Repository Overview
kind: raw-source
status: captured
source_url: https://github.com/duckdb/duckdb-wasm
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Records the browser-side DuckDB stack used for client-side analytics and interactive data workflows in docs-oriented apps.
---

## Source Record

- Source URL: `https://github.com/duckdb/duckdb-wasm`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

DuckDB-Wasm is relevant to the repo's docs-app stack because it enables in-browser analytical querying, Arrow/Parquet interoperability, and client-side data exploration. That is useful for interactive docs experiences and lightweight embedded analytics.

## Key Excerpts

> "DuckDB-Wasm brings DuckDB to every browser thanks to WebAssembly."

> "Duckdb-Wasm speaks Arrow fluently, reads Parquet, CSV and JSON files... and has been tested with Chrome, Firefox, Safari and Node.js."

> "DuckDB-Wasm default mode is single threaded. Multithreading is at the moment still experimental."

> "A growing subset of extensions, either core, community or external, are supported for DuckDB-Wasm."

## Capture Notes

- The GitHub repository page included the rendered README inline; the note uses the README content, not the surrounding GitHub chrome.
- The most stack-relevant details are browser execution, Arrow/Parquet support, extension loading, and the current single-threaded default.
- The captured page also surfaced the repo structure, including TypeScript API, shell, app, and React hook packages.
