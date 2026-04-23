# Docs App Stack Inventory

## Purpose
- Inventory the current docs application stack with emphasis on framework/runtime choices, the in-browser DuckDB playground, and the authored playground page contract.

## High-value paths

### Framework and package surface
| Path | Inventory role |
| --- | --- |
| `docs/AGENTS.md` | Canonical stack summary, docs app structure, MDX component contract, SQL playground architecture notes, and docs-specific operational rules. |
| `docs/package.json` | Actual package/runtime inventory: scripts, engine constraints, pinned dependency versions, and dev tooling. |

### Interactive data stack
| Path | Inventory role |
| --- | --- |
| `docs/lib/duckdb.ts` | DuckDB-WASM singleton, query runner, Parquet registration, multi-table loading, timeout reset, and teardown behavior. |
| `docs/components/mdx/sql-playground.tsx` | Client-only SQL playground UI, lazy engine init, query execution, result rendering, chart toggle, and cleanup. |

### Authored page contract
| Path | Inventory role |
| --- | --- |
| `docs/content/docs/playground.mdx` | User-facing positioning for the playground, data modes, and navigation handoff to other guides. |

## Notes
- The docs app stack is centered on Fumadocs 16, Next.js 16 App Router, pnpm, Tailwind CSS v4.2, Mermaid 11, DuckDB-WASM, Observable Plot, Recharts, and CVA-backed UI components.
- `docs/lib/duckdb.ts` keeps one shared in-browser DuckDB instance, validates Parquet table identifiers, supports multi-table registration with progress callbacks, and resets the session on timeout or explicit destroy.
- `playground.mdx` frames the page as a browser-first rehearsal lane, not an auto-mounted local warehouse.

## Planned wiki coverage
- `wiki/topics/docs-app-stack.md`
- `wiki/topics/docs-generator-internals.md`
- `wiki/topics/playground-lane.md`

## Provenance
- `docs/AGENTS.md`
- `docs/package.json`
- `docs/lib/duckdb.ts`
- `docs/components/mdx/sql-playground.tsx`
- `docs/content/docs/playground.mdx`
