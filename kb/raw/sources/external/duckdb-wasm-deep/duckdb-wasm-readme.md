---
title: DuckDB-Wasm README
kind: raw-source
status: captured
source_url: https://github.com/duckdb/duckdb-wasm/blob/main/README.md
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Summarizes the upstream project README, including browser capabilities, wasm-specific behavior differences, and extension/runtime support.
---

## Source Record

- Source URL: `https://github.com/duckdb/duckdb-wasm/blob/main/README.md`
- Fetch method: `webfetch` in markdown mode against the raw GitHub README to avoid page chrome
- Capture date: `2026-04-14`

## Why It Matters

The README is the most complete upstream narrative source for DuckDB-Wasm. It adds the practical differences between native DuckDB and the wasm build, especially around HTTP behavior, extension loading, sandboxing, and thread support.

## Key Excerpts

> "DuckDB-Wasm brings DuckDB to every browser thanks to WebAssembly."

> "Duckdb-Wasm speaks Arrow fluently, reads Parquet, CSV and JSON files backed by Filesystem APIs or HTTP requests and has been tested with Chrome, Firefox, Safari and Node.js."

> "Requests are always upgraded to HTTPS."

> "DuckDB-Wasm default mode is single threaded. Multithreading is at the moment still experimental."

## Capture Notes

- The README is where the wasm-vs-native behavior delta is described most concretely.
- Extension loading is lazy in wasm, and some core features that feel bundled in native DuckDB may autoload over the network here.
- The sandboxed runtime and browser networking constraints are treated as first-order design considerations, not edge cases.
- The repository structure section is useful for separating the core wasm library, TypeScript API, shell, app, and React hooks packages.
