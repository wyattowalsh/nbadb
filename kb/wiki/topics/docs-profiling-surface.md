---
title: Docs Profiling Surface
tags:
  - kb
  - topics
  - docs
  - admin
  - profiling
aliases:
  - Admin Profiling Surface
  - Table Profiling Surface
kind: concept
status: active
updated: 2026-04-22
source_count: 8
---

# Docs Profiling Surface

Use this note when the question is "how does `/admin/profiling` find, shape, order, and render table-profile data?"

## At a glance
| Concern | Canonical owner | Current behavior |
| --- | --- | --- |
| JSON lookup | `docs/app/(admin)/admin/profiling/page.tsx` + `docs/lib/admin/files.ts` | tries three paths in order, skips missing files, throws on malformed JSON |
| profile payload shape | `docs/lib/admin/types.ts` + `src/nbadb/docs_gen/table_profile.py` | `TableProfile[]` with nested `ColumnProfile[]` |
| profile generation | `src/nbadb/docs_gen/autogen.py` + `src/nbadb/docs_gen/table_profile.py` | writes JSON only when the DuckDB database exists |
| layer labeling | `src/nbadb/docs_gen/table_profile.py` | derived from table-name prefix |
| layer display order | `docs/app/(admin)/admin/profiling/page.tsx` | `raw`, `staging`, `dimension`, `bridge`, `fact`, `aggregate`, `analytics`, `other` |
| per-layer rendering | `docs/app/(admin)/admin/profiling/profiling-layer-table.tsx` | TanStack table showing table name, rows, columns, and a six-chip column preview |

## JSON artifact lookup order
`/admin/profiling` is JSON-backed only. It does not open DuckDB or query the warehouse at request time.

The page loader resolves candidate files in this order:
1. `table-profile.generated.json`
2. `../table-profile.generated.json`
3. `lib/admin/table-profile.generated.json`

`readFirstJson()` is the contract boundary for that search:
- missing files (`ENOENT`) are skipped
- the first readable JSON file wins
- malformed JSON or other read failures throw immediately
- the loader returns `null` only when every candidate path is missing

Generation and lookup are related but not identical:
- with the canonical docs root `docs/content/docs`, `docs-autogen` writes the profiling artifact to `docs/table-profile.generated.json`
- with a non-canonical docs root, `docs-autogen` writes to `<docs_root>/_generated/table-profile.generated.json`
- the profiling page only knows about the three hard-coded lookup locations above, so alternate output paths are not auto-discovered unless copied into one of those locations

## `TableProfile` contract
The docs app treats profiling as a shared typed contract, not an ad hoc page-local shape.

### Type shape
`docs/lib/admin/types.ts` defines:

```ts
type ColumnProfile = {
  name: string;
  type: string;
  nullPct: number;
};

type TableProfile = {
  table: string;
  layer: string;
  rowCount: number;
  columnCount: number;
  columns: ColumnProfile[];
};
```

### Generator-side expectations
`TableProfileGenerator.generate()` emits one object per physical DuckDB table with:
- `table`: the table name from `information_schema.tables`
- `layer`: prefix-derived logical layer
- `rowCount`: `COUNT(*)`
- `columnCount`: number of columns returned from `information_schema.columns`
- `columns`: ordered column metadata with `name`, `type`, and `nullPct`

Two important details:
- column order is stable because generator-side column discovery orders by `ordinal_position`
- `nullPct` is always present in the artifact, but the current UI does not render it

## Layer labeling and ordering
Layer assignment and layer display order are separate concerns.

### Generator-side layer labeling
The generator maps table-name prefixes to layer labels like this:
- `raw_` -> `raw`
- `stg_` -> `staging`
- `dim_` -> `dimension`
- `fact_` -> `fact`
- `bridge_` -> `bridge`
- `agg_` -> `aggregate`
- `analytics_` -> `analytics`
- everything else -> `other`

### Page-side layer ordering
After loading the profiles, the page groups them by `profile.layer` and sorts the groups with this explicit rank:
1. `raw`
2. `staging`
3. `dimension`
4. `bridge`
5. `fact`
6. `aggregate`
7. `analytics`
8. `other`

That means bridge tables render before fact tables even though the generator's prefix matcher checks `fact_` before `bridge_`. The matcher only decides the label; the page decides the visual order.

## Empty-state behavior
The profiling surface has a deliberate soft-fail path.

### Page-level empty state
If `getTableProfiles()` resolves to `[]`, the page:
- still renders the profiling header
- replaces all KPI cards and layer tables with a single card
- shows `No profiling data available`
- points the operator at:

```bash
uv run nbadb docs-autogen --docs-root docs/content/docs
```

This is a missing-artifact condition, not a fatal page error.

### Broken JSON behavior
If a candidate JSON file exists but cannot be read or parsed, `readFirstJson()` throws. That path is intentionally not treated as an empty state.

### Table-level empty state
`ProfilingLayerTable` renders through the shared `DataTable` component. `DataTable` has its own fallback row, `No rows are available for this view yet.`

In practice, `/admin/profiling` almost never uses that row-level fallback because the page short-circuits before rendering any layer cards when the loaded profile list is empty.

## `ProfilingLayerTable` rendering
Each layer card renders one `ProfilingLayerTable` with the grouped `TableProfile[]` for that layer.

The table columns are:
- `Table`: monospace table name
- `Rows`: localized numeric `rowCount`
- `Columns`: numeric `columnCount`
- `Column profile`: up to six inline chips showing `column.name` and `column.type`

Current rendering rules:
- the chip preview truncates after six columns
- when a table has more than six columns, the UI adds a `+N more` overflow chip
- `nullPct` is not shown anywhere in the current layer table
- sorting and pagination come from the shared TanStack-based `DataTable`
- default page size is 20 rows
- pagination controls only appear when a layer has more than one page of rows

## Maintainer cues
- Treat the JSON path search order as part of the operational contract. Changing it changes which generated artifact wins.
- Keep `TableProfile` in `docs/lib/admin/types.ts` as the shared consumer contract; avoid page-local redefinitions.
- If the profiling UI ever needs nullability insight, `nullPct` is already available in the artifact and only needs a rendering decision.
- If alternate docs roots become first-class, the page lookup order and generator output path logic need to be reconciled explicitly.
- Treat `docs/table-profile.generated.json` as an optional command-owned artifact, not as a permanently present canonical file.

## Related notes
- [[wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[wiki/topics/docs-telemetry-health|Docs Telemetry and Health]]
- [[wiki/topics/docs-generator-internals|Docs Generator Internals]]
- [[wiki/topics/docs-autogen|Docs Autogen]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| profiling page lookup order, KPI totals, layer grouping, display order, and page-level empty state | `docs/app/(admin)/admin/profiling/page.tsx` | canonical profiling page loader and server-rendered UI |
| missing-file skip behavior and hard failure on malformed JSON | `docs/lib/admin/files.ts` | shared JSON fallback primitive |
| `TableProfile` and `ColumnProfile` type contract | `docs/lib/admin/types.ts` | shared docs-admin telemetry types |
| generator-side layer derivation, row counts, column counts, ordered columns, and `nullPct` calculation | `src/nbadb/docs_gen/table_profile.py` | canonical table-profile artifact generator |
| generated artifact output path rules and "only write when DB exists" behavior | `src/nbadb/docs_gen/autogen.py` | profiling artifact orchestration |
| grouped docs-generator bridge | `raw/extracts/internal/docs-generator-manifest.md` | KB bridge for docs-autogen ownership and optional profiling output |
| per-layer table rendering, six-chip preview, and hidden `nullPct` detail | `docs/app/(admin)/admin/profiling/profiling-layer-table.tsx` | profiling table component |
| sorting, pagination, 20-row page size, and row-level empty fallback | `docs/components/admin/data-table.tsx` | shared TanStack table wrapper |
