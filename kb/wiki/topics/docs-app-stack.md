---
title: Docs App Stack
tags:
  - kb
  - topics
  - docs
  - frontend
aliases:
  - Docs Site Stack
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Docs App Stack

Use this note when you need the current docs-app architecture, package/runtime constraints, or the browser SQL playground mechanics.

## Stack at a glance
| Layer | Current repo evidence | Role |
| --- | --- | --- |
| Framework | Fumadocs 16 + Next.js 16 App Router | docs shell, routing, MDX content |
| UI | React 19, Tailwind CSS v4, CVA, Radix | component layer and styling primitives |
| Visualization | Mermaid 11, Observable Plot, Recharts | diagrams, charts, admin views |
| Browser data lane | `@duckdb/duckdb-wasm` | in-browser SQL sandbox and Parquet reads |
| Tooling | pnpm, Node `>=22`, TypeScript, ESLint, Prettier, Vitest | app build, lint, test, typecheck |

## Repo-specific shape
- `docs/` is its own app, separate from the Python package runtime.
- `docs/content/docs/` mixes hand-authored guides with generated contract pages.
- `docs/lib/duckdb.ts` owns the shared DuckDB-WASM singleton, query execution, remote Parquet registration, timeout-triggered reset, and teardown.
- `docs/content/docs/playground.mdx` positions the SQL Playground as a browser-first warm-up lane.

## Playground model
- Everything runs inside the browser tab with DuckDB-WASM.
- The page prefers published sample Parquet when available.
- When hosted sample Parquet is unavailable, it falls back to inline demo rows while preserving nbadb-style table names and join shapes.
- The next handoff is explicit: move to local DuckDB, Parquet usage, or schema pages once the query shape is locked in.

## Maintainer rules
- Treat `docs/AGENTS.md` as the stack contract for the web app.
- Treat [[wiki/topics/docs-autogen|Docs Autogen]] as the companion note for generated docs ownership.
- Do not assume the playground reads the local warehouse automatically.
- Keep docs-app questions separate from the Python warehouse stack unless the issue crosses the docs generator boundary.

## Related notes
- [[wiki/topics/project-overview|Project Overview]]
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]
- [[wiki/tooling/duckdb-polars-pandera-stack|DuckDB, Polars, and Pandera in nbadb]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| framework, structure, interactive components, admin surface | `docs/AGENTS.md` | docs app contract |
| runtime constraints, scripts, dependency versions | `docs/package.json` | package truth for the docs app |
| DuckDB-WASM singleton and query runner | `docs/lib/duckdb.ts` | browser SQL engine behavior |
| playground positioning and sample-data behavior | `docs/content/docs/playground.mdx` | user-facing sandbox framing |
| docs surface as authored + generated pages | `raw/extracts/internal/docs-surface-inventory.md` | KB source inventory |
| public docs homepage framing | `raw/sources/external/distribution/nbadb-docs-site.md` | external capture |
| docs entry-page contract and generated-page warning | `raw/sources/external/public-contract/nbadb-public-contract-docs.md` | external capture |
| docs-app upstream stack | `raw/sources/external/docs-app-stack/` | second-wave raw captures |
