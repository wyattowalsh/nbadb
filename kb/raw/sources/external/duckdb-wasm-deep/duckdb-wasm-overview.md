---
title: DuckDB-Wasm Overview
kind: raw-source
status: captured
source_url: https://duckdb.org/docs/stable/clients/wasm/overview
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Establishes the top-level runtime model, entry points, and hard browser constraints for DuckDB-Wasm.
---

## Source Record

- Source URL: `https://duckdb.org/docs/stable/clients/wasm/overview`
- Fetch method: `webfetch` in markdown mode via DuckDB's current raw Markdown mirror after redirect
- Capture date: `2026-04-14`

## Why It Matters

This page is the shortest official summary of what DuckDB-Wasm is, how it is packaged, and the limits that shape any browser-side design. It is the right anchor note before reading the lower-level ingestion, query, and bindings docs.

## Key Excerpts

> "DuckDB has been compiled to WebAssembly, so it can run inside any browser on any device."

> "DuckDB-Wasm offers a layered API, it can be embedded as a JavaScript + WebAssembly library, as a Web shell, or built from source according to your needs."

> "By default, the WebAssembly client only uses a single thread."

> "WebAssembly limits the amount of available memory to 4 GB and browsers may impose even stricter limits."

## Capture Notes

- The stable URL now redirects to DuckDB's `current` docs; the raw Markdown mirror yielded the cleanest capture.
- The most decision-relevant details are the layered packaging model, the single-thread default, and browser memory ceilings.
- The page points readers outward to the GitHub repo and the generated API docs rather than duplicating implementation detail.
