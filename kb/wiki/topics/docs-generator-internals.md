---
title: Docs Generator Internals
tags:
  - kb
  - topics
  - docs
  - generation
  - internals
aliases:
  - nbadb Docs Generator Internals
  - docs-gen Internals
kind: concept
status: active
updated: 2026-04-14
source_count: 10
---

# Docs Generator Internals

Use this note when the issue is inside the docs-generation codepath itself rather than in a hand-authored docs page.

## Mental model
- `src/nbadb/docs_gen/autogen.py` is the orchestrator. It resolves output roots, calls each generator, and writes artifacts only when normalized bytes changed.
- The generator lane is intentionally split:
  - Python discovery and generation in `src/nbadb/docs_gen/*.py`
  - lightweight docs-app rendering from generated JSON plus small MDX stubs
- With the canonical docs root `docs/content/docs`, machine-readable outputs land in `docs/lib/generated/`.

## Generator map
| Module | Main job | Key outputs or behavior |
| --- | --- | --- |
| `autogen.py` | fan-out coordinator | schema stubs, dictionary stubs, ER/lineage pages, generated JSON, site metrics |
| `schema_docs.py` | discover Pandera `DataFrameModel` classes per tier | schema reference JSON plus MDX stubs |
| `data_dictionary.py` | extract field metadata from schema columns | dictionary JSON plus MDX stubs |
| `er_diagram.py` | read `fk_ref` metadata from star schemas | `er-auto.mdx` and `schema.json` |
| `lineage.py` | merge schema metadata lineage with SQLGlot SQL analysis | `lineage-auto.mdx`, `lineage.json`, `schema-coverage.json` |
| `site_metrics.py` | compute homepage scoreboard and inventory | `docs/lib/site-metrics.generated.ts` |
| `table_profile.py` | inspect a real DuckDB database if present | optional `table-profile.generated.json` |

## Internal rules worth remembering
- Writes are deterministic: content is newline-normalized, compared against the existing file, then reported as `updated` or `unchanged`.
- Schema and data-dictionary pages are JSON-first by design. The MDX files are small stubs that import JSON and hand rendering to React components.
- `lineage-auto.mdx` is not just raw lineage output; `autogen.py` appends a coverage note derived from lineage outputs vs schema-backed outputs.
- `table_profile.py` only runs when the target DuckDB file exists.

## Related notes
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/playground-lane|Playground Lane]]

## Provenance
| Claim or section | Repo or raw source | Notes |
|------------------|--------------------|-------|
| orchestrator flow, path resolution, deterministic writes | `src/nbadb/docs_gen/autogen.py` | canonical generator entrypoint |
| schema discovery and JSON-first stub pattern | `src/nbadb/docs_gen/schema_docs.py` | schema generation |
| field metadata extraction and dictionary stub pattern | `src/nbadb/docs_gen/data_dictionary.py` | dictionary internals |
| hybrid schema metadata + SQLGlot lineage analysis | `src/nbadb/docs_gen/lineage.py` | lineage mechanics |
| FK-driven ER generation | `src/nbadb/docs_gen/er_diagram.py` | ER generator behavior |
| homepage metrics derivation | `src/nbadb/docs_gen/site_metrics.py` | generated TS module internals |
| conditional database-backed profiling | `src/nbadb/docs_gen/table_profile.py` | profile generation logic |
| docs app contract for generated artifacts | `docs/AGENTS.md` | consumer-side contract |
| docs app stack captures | `raw/sources/external/docs-app-stack/` | external stack context |
| internal docs app inventory | `raw/extracts/internal/docs-app-stack-inventory.md` | grouped repo-local inventory |
