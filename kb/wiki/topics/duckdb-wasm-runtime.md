---
title: DuckDB-WASM Runtime
tags:
  - kb
  - topics
  - docs
  - duckdb
  - wasm
  - runtime
aliases:
  - Docs DuckDB Runtime
  - SQL Playground DuckDB Runtime
kind: concept
status: active
updated: 2026-04-14
source_count: 5
---

# DuckDB-WASM Runtime

Use this note when the question is "How does the docs SQL sandbox actually execute?" rather than "What does the playground page teach?"

## Runtime contract
The docs DuckDB layer is the browser-only execution engine behind `SqlPlayground`. It owns one shared DuckDB-WASM instance per active tab session, registers optional Parquet-backed tables, runs SQL through short-lived connections, and tears the engine down on timeout, cancel, or page cleanup.

## Singleton and bundle selection
- `docs/lib/duckdb.ts` keeps module-scoped `dbInstance` and `initPromise` values so concurrent callers share one lazy initialization path.
- `getDb()` uses `duckdb.getJsDelivrBundles()` plus `duckdb.selectBundle(...)` to choose the right CDN bundle for the current browser.
- The selected worker entry is wrapped in a Blob URL that calls `importScripts(bundle.mainWorker)`, then passed into `new Worker(...)`.
- `AsyncDuckDB` is instantiated once from that worker and then reused by every later query or Parquet registration until the session is reset.

## Worker lifecycle and reset semantics
- The worker is created only during initialization and is held indirectly by the shared `AsyncDuckDB` instance.
- Failed initialization is cleaned up immediately: either `db.terminate()` or `worker.terminate()` runs before the error is rethrown.
- `destroyDb()` is the hard reset path. It increments `initGeneration`, clears `initPromise`, nulls `dbInstance`, and terminates the current DuckDB instance.
- `initGeneration` prevents races: if a reset happens while initialization is still in flight, the pending init throws a cancellation error instead of reviving a stale engine.
- `components/mdx/sql-playground.tsx` calls `destroyDb()` on explicit cancel and again on component unmount, so the browser worker and memory do not survive page exit.

## Timeout reset behavior
- `runQuery()` races `conn.query(sql)` against a timer when `timeoutMs` is provided.
- On timeout, the runtime does not just cancel one statement. It destroys the entire shared DuckDB session and rejects with a reset-specific error.
- The playground UI treats that as a fresh-session boundary: it clears results, marks the engine as not ready, and forces the next run to initialize DuckDB again.

## Parquet registration path
- `registerParquet(tableName, url)` is the remote-data entry point.
- Table names are validated against `^[a-z_][a-z0-9_]*$` before any SQL is built.
- The URL is quote-escaped, then the runtime executes `CREATE OR REPLACE TABLE ... AS SELECT * FROM read_parquet(...)` inside DuckDB-WASM.
- `registerMultipleParquet(...)` loads tables sequentially and reports progress back to `SqlPlayground`, which surfaces load status in the toolbar.

## Query path
1. A docs page renders `<SqlPlayground ... />`.
2. `SqlPlayground` lazy-imports `@/lib/duckdb` and calls `getDb()` during first run.
3. If the page declared `tables` or `parquetUrl` plus `tableName`, the component registers those Parquet sources before marking the engine ready.
4. The run action calls `runQuery(query, { timeoutMs: 15000 })`.
5. `runQuery()` opens a fresh connection from the shared DuckDB instance, executes SQL, converts Arrow-like results into `{ columns, rows }`, and closes the connection unless a timeout already forced session teardown.
6. The component slices displayed rows to 1,000, records execution time, and optionally infers a chart view from the result shape.

## Relationship to playground pages
- `docs/content/docs/playground.mdx` is the main composition layer, not the runtime.
- That page mounts two playgrounds:
  - a built-in self-contained SQL drill with inline demo rows
  - a second drill that either registers published sample Parquet tables or falls back to inline warehouse-shaped demo tables
- The page gets those query packs and table declarations from `docs/lib/playground-examples.ts`.
- The important boundary is:
  - `playground.mdx` decides the teaching flow and which examples/tables to expose
  - `components/mdx/sql-playground.tsx` owns UI state, cancel/reset handling, and progress display
  - `docs/lib/duckdb.ts` owns the actual DuckDB-WASM lifecycle and execution contract

## Maintainer takeaways
- Treat `docs/lib/duckdb.ts` as the canonical runtime boundary for browser SQL execution.
- Treat timeout as destructive by design: it resets the whole in-browser database, not just the active query.
- Treat Parquet registration as explicit opt-in page wiring, not ambient access to the local warehouse.
- If a playground bug smells like stale state, race conditions, or leaked workers, inspect `initGeneration`, `destroyDb()`, and the component unmount/cancel paths first.

## Related notes
- [[wiki/topics/playground-lane|Playground Lane]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-search-surface|Docs Search Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| singleton, bundle selection, worker creation, timeout reset, Parquet registration, `destroyDb()` | `docs/lib/duckdb.ts` | canonical runtime implementation |
| query execution flow, cancel handling, unmount teardown, progress UI, 15s timeout wiring | `docs/components/mdx/sql-playground.tsx` | component layer over the runtime |
| page purpose, browser-only framing, dual playground layout, handoff to real-data pages | `docs/content/docs/playground.mdx` | canonical user-facing playground contract |
| built-in examples, Parquet table declarations, fallback behavior when sample data is absent | `docs/lib/playground-examples.ts` | page composition inputs |
| docs-site contract for `SqlPlayground` and `lib/duckdb.ts` responsibilities | `docs/AGENTS.md` | maintainer-facing architecture guide |
