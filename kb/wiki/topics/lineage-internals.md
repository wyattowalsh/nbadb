---
title: Lineage Internals
tags:
  - kb
  - topics
  - lineage
  - docs
  - internals
aliases:
  - nbadb Lineage Internals
  - data lineage internals
kind: concept
status: active
updated: 2026-04-22
source_count: 16
---

# Lineage Internals

Use this note when the question is not "what is this table upstream of?" but "how does the repo compute and publish lineage at all?"

## Mental model
- There are two adjacent but distinct lineage surfaces in the repo.
- The transform dependency graph is a `depends_on` graph over transformer declarations. It answers execution-order and blast-radius questions.
- The docs lineage generator is a hybrid view. It combines star-schema column metadata with SQLGlot parsing of transformer SQL to produce docs-facing lineage JSON and Mermaid diagrams.
- The authored docs pages in `docs/content/docs/model/lineage/` are the reader-facing guide rails around those generated artifacts.

## 1. Transform dependency graph
`src/nbadb/core/transform_dependency_graph.py` builds a machine-readable graph from discovered transformers.

### What it uses
- `nbadb.orchestrate.transformers.discover_all_transformers()` walks `dimensions`, `facts`, `derived`, and `views`, instantiates concrete `BaseTransformer` subclasses, and keys them by `output_table`.
- `BaseTransformer` defines the declarative contract: `output_table` plus `depends_on`.

### What it emits
- One node per transformer output table.
- One edge per declared dependency.
- Dependency kinds split into `transform_output`, `staging`, `raw`, and `unresolved`.
- Summary data including family breakdown, roots, leaves, cycles, and a topological `execution_order` when the graph is acyclic.

### Why it matters
- This is the repo's explicit dependency declaration layer.
- It is the right artifact for scheduler reasoning, dependency audits, and "what downstream transform consumes this output?" questions.
- It is not the same implementation as docs lineage generation, even though both start from transformer discovery.

## 2. SQLGlot-based lineage generation
`src/nbadb/docs_gen/lineage.py` owns the docs lineage generator.

### SQL lane
- `SqlLineageAnalyzer.analyze()` discovers all transformers, filters to `SqlTransformer` instances with non-empty `_SQL`, and parses each query with SQLGlot using the DuckDB dialect.
- It walks parsed statements to collect:
  - source tables from `exp.Table`
  - output column aliases from the outer `SELECT`
  - CTE names so CTE aliases are excluded from source-table lineage
- The result is keyed by `output_table` and stores `source_tables`, `columns`, and `class_name`.

### Important boundary
- This is inferred lineage from actual SQL text, not from `depends_on`.
- That means the docs lineage generator can reflect the tables the SQL really references, while the dependency graph reflects the dependencies the transformer declares.
- In practice those should usually align, but they are maintained through different code paths.

## 3. Schema source metadata
The second input to docs lineage is Pandera field metadata.

### Where it lives
- Star-schema classes under `src/nbadb/schemas/star/*.py` attach metadata like:
  - `source`: upstream endpoint/result-set/field or `derived.*`
  - `fk_ref`: foreign-key target
  - `description`: human explanation
- Example patterns show up in files such as `dim_player.py` and `fact_player_game_traditional.py`.
- Staging schemas also carry `source` and `fk_ref`, but `LineageGenerator.build_lineage_graph()` currently discovers `nbadb.schemas.star` classes, not staging classes.

### How `lineage.py` reads it
- `_discover_schemas()` imports `nbadb.schemas.star` modules and collects `pa.DataFrameModel` subclasses.
- `build_lineage_graph()` converts class names to table names, calls `to_schema()`, and reads each column's metadata.
- When `metadata["source"]` looks like `Endpoint.ResultSet.FIELD`, it is split into:
  - `endpoint`
  - `result_set`
  - `field`
- `fk_ref` is copied through when present.

### Practical meaning
- Schema metadata gives the docs generator a column-to-source view even when the transform logic is not directly recoverable from SQL aliases alone.
- `derived.*` sources mark modeled fields such as surrogate keys or SCD2 bookkeeping rather than raw NBA API fields.

## 4. How generated lineage pages relate to code
The lineage docs section has both authored and generated layers.

### Generator-owned page
- `docs/content/docs/model/lineage/lineage-auto.mdx` is generator-owned.
- `LineageGenerator.generate_mdx()` renders the extraction and transform Mermaid diagrams.
- `src/nbadb/docs_gen/autogen.py` wraps that output with coverage notes comparing lineage outputs to schema-backed tables.

### Machine-readable payloads
- During normal docs generation, `autogen.py` writes `lineage.json` and `schema-coverage.json` into the resolved generated-data directory, which is `docs/lib/generated/` for the canonical docs root.
- `LineageGenerator.write()` can also write a `lineage.json` next to the MDX page, but that is not the main `docs-autogen` path used by the repo.

### Authored companion pages
- `docs/content/docs/model/lineage/index.mdx` frames the section and explicitly routes users from curated pages to the exhaustive generated map.
- `table-lineage.mdx` is the hand-authored possession-chain explanation layer.
- `column-lineage.mdx` explains field-level tracing and points readers back to metadata in code.

### Important repo-local nuance
- The authored docs sometimes talk about lineage in terms of schema metadata plus `depends_on` declarations.
- The current code is more split than that:
  - dependency-graph artifacts come from `depends_on`
  - generated docs lineage comes from star-schema metadata plus SQLGlot parsing of `_SQL`

## 5. Reading the whole lineage stack
Use this sequence when debugging lineage internals:

1. Check `transform/base.py` and the concrete transformer for declared `depends_on`, `output_table`, and `_SQL`.
2. Check `orchestrate/transformers.py` to confirm the transformer is discoverable.
3. Check the relevant star schema class for `metadata["source"]` and `fk_ref`.
4. Check `docs_gen/lineage.py` to see whether the question is answered by schema lineage, SQL lineage, or both.
5. Check `docs_gen/autogen.py` to see where the final docs artifacts are written and how coverage notes are added.
6. Check the authored docs pages under `docs/content/docs/model/lineage/` to understand how the generated data is presented to readers.

## Related notes
- [[wiki/topics/docs-generator-internals|Docs Generator Internals]]
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/project-overview|Project Overview]]
- [[wiki/topics/model-audit|Model Audit]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| transform dependency graph structure, dependency kinds, roots/leaves/cycles/execution order | `src/nbadb/core/transform_dependency_graph.py` | canonical dependency-graph implementation |
| transformer discovery across dimensions/facts/derived/views | `src/nbadb/orchestrate/transformers.py` | shared discovery entrypoint |
| `BaseTransformer`, `SqlTransformer`, `depends_on`, `_SQL` contract | `src/nbadb/transform/base.py` | transformer declaration surface |
| SQLGlot lineage parsing, CTE exclusion, combined lineage dict, Mermaid generation | `src/nbadb/docs_gen/lineage.py` | docs lineage generator |
| coverage note injection and final `docs/lib/generated` artifact writes | `src/nbadb/docs_gen/autogen.py` | normal docs-autogen path |
| grouped lineage and audit inventory | `raw/extracts/internal/lineage-audit-inventory.md` | internal manifest for this topic cluster |
| star-schema `source` and `fk_ref` metadata patterns | `src/nbadb/schemas/star/dim_player.py` | example dimension schema |
| star-schema field-level source metadata for fact outputs | `src/nbadb/schemas/star/fact_player_game_traditional.py` | example fact schema |
| staging-schema metadata pattern used elsewhere in the warehouse | `src/nbadb/schemas/staging/player.py` | useful contrast with star-only discovery in `lineage.py` |
| staging-schema metadata pattern used elsewhere in the warehouse | `src/nbadb/schemas/staging/box_score.py` | useful contrast with star-only discovery in `lineage.py` |
| generated vs curated lineage page boundary | `docs/content/docs/model/lineage/index.mdx` | docs presentation layer |
| generated vs curated lineage page boundary | `docs/content/docs/model/lineage/table-lineage.mdx` | docs presentation layer |
| generated vs curated lineage page boundary | `docs/content/docs/model/lineage/column-lineage.mdx` | docs presentation layer |
| generated vs curated lineage page boundary | `docs/content/docs/model/lineage/lineage-auto.mdx` | docs presentation layer |
| generator-lane framing and KB style/context | `wiki/topics/docs-generator-internals.md` | local note conventions and related concepts |
| generator-lane framing and KB style/context | `wiki/topics/docs-autogen.md` | local note conventions and related concepts |
