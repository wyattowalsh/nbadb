---
title: DuckDB-Wasm Repository Overview
kind: raw-source
status: captured
source_url: https://github.com/duckdb/duckdb-wasm
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Records the browser-side DuckDB stack that enables in-browser SQL, Arrow, and Parquet workflows for interactive docs or embedded analytics.
---

## Source Record

- Source URL: `https://github.com/duckdb/duckdb-wasm`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

DuckDB-Wasm is relevant to the docs-framework stack because it enables fully client-side analytical querying in browser contexts. That makes it useful for interactive docs experiences, embedded data explorers, and lightweight analytical demos without a server-side query layer.

## Key Excerpts

> "DuckDB-Wasm brings DuckDB to every browser thanks to WebAssembly."

> "Duckdb-Wasm speaks Arrow fluently, reads Parquet, CSV and JSON files... and has been tested with Chrome, Firefox, Safari and Node.js."

> "DuckDB-Wasm default mode is single threaded. Multithreading is at the moment still experimental."

> "A growing subset of extensions, either core, community or external, are supported for DuckDB-Wasm"

## Capture Notes

- The rendered GitHub page included the README inline; the note summarizes README content rather than repository chrome.
- The most stack-relevant details are browser execution, file-format support, runtime extension loading, and the current single-threaded default.
- The repo structure also surfaced separate packages for the TypeScript API, shell, app, and React hooks.
