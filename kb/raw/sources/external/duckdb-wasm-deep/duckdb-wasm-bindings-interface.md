---
title: DuckDB-Wasm DuckDBBindings Interface
kind: raw-source
status: captured
source_url: https://shell.duckdb.org/docs/interfaces/index.DuckDBBindings.html
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the low-level bindings surface that exposes connection, query, file registration, ingestion, and export primitives under the higher-level API.
---

## Source Record

- Source URL: `https://shell.duckdb.org/docs/interfaces/index.DuckDBBindings.html`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This interface page exposes the lower-level operational surface beneath the higher-level async client helpers. It is the best compact reference for what the wasm bindings can do around lifecycle control, file registration, query execution, streaming, and result extraction.

## Key Excerpts

> "interface DuckDBBindings"

> "runQuery(conn: number, text: string): Uint8Array"

> "registerFileURL(name: string, url: string, proto: DuckDBDataProtocol, directIO: boolean): void"

> "copyFileToBuffer(name: string): Uint8Array"

## Capture Notes

- The method list clusters naturally into runtime lifecycle (`instantiate`, `open`, `reset`), connection/query control (`connect`, `runQuery`, `startPendingQuery`), and file/data operations (`registerFile*`, `insert*`, `copyFileToBuffer`).
- The interface shows that file registration is a first-class primitive, not just a convenience helper layered elsewhere.
- The presence of pending-query and polling methods confirms explicit support for non-blocking query orchestration below the higher-level API.
- `copyFileToBuffer` and related file methods explain how exports come back out of the wasm runtime after SQL writes them.
