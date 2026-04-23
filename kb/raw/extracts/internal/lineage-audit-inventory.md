# Lineage and Audit Inventory

## Purpose
- Grouped internal extract manifest for lineage generation, transform dependency inspection, endpoint coverage classification, model-audit reuse, and the docs/generated artifact boundary.

## High-value paths

### Lineage generation and dependency graph
| Path | Inventory role |
| --- | --- |
| `src/nbadb/docs_gen/lineage.py` | Primary lineage generator: discovers star schemas, reads `metadata["source"]` and `fk_ref`, merges SQLGlot-derived `SqlTransformer` lineage, and writes the generated lineage docs payloads. |
| `src/nbadb/core/transform_dependency_graph.py` | Raw transform-graph inventory: classifies dependency kinds, computes roots/leaves/cycles/execution order, and writes the transform dependency JSON artifact. |

### Coverage and audit engines
| Path | Inventory role |
| --- | --- |
| `src/nbadb/core/endpoint_coverage.py` | Runtime/extractor/staging/model ownership inventory for stats, static, and live surfaces; emits coverage matrix, summary, and report artifacts plus star-schema coverage breakdown. |
| `src/nbadb/core/model_audit.py` | Higher-order audit engine that reuses endpoint coverage and lineage, then inventories runtime surfaces, staging surfaces, model surfaces, and column contracts with optional probe/build validation. |

### Docs lineage surfaces
| Path | Inventory role |
| --- | --- |
| `docs/content/docs/model/lineage/index.mdx` | Route selector for the lineage section; explains curated vs generated lineage surfaces. |
| `docs/content/docs/model/lineage/table-lineage.mdx` | Hand-authored table-level lineage companion page. |
| `docs/content/docs/model/lineage/column-lineage.mdx` | Hand-authored field-level lineage companion page; also explains metadata-based lineage encoding. |
| `docs/content/docs/lineage/lineage-auto.mdx` | Generator-owned exhaustive lineage page rendered from `LineageGenerator`. |
| `docs/content/docs/model/lineage/meta.json` | Navigation ordering for the lineage docs section. |
| `docs/components/site/docs-generated-coverage.tsx` | Docs UI bridge that surfaces the schema-coverage gap on lineage/schema pages from generated JSON. |

### Generated JSON and artifact sinks
| Path | Inventory role |
| --- | --- |
| `docs/lib/generated/lineage.json` | Machine-readable combined lineage payload keyed by output table, with `schema_lineage` and/or `sql_lineage` entries. |
| `docs/lib/generated/schema-coverage.json` | Machine-readable lineage-vs-schema-reference gap summary used by the docs coverage surface. |
| transform-dependency graph output written by `src/nbadb/core/transform_dependency_graph.py` | Output sink for transform dependency graph generation when that artifact is refreshed locally. |
| `artifacts/endpoint-coverage/endpoint-coverage-matrix.json` | Output sink for per-surface endpoint coverage rows. |
| `artifacts/endpoint-coverage/endpoint-coverage-summary.json` | Output sink for endpoint coverage rollups, ownership counts, and star-schema coverage. |
| `artifacts/endpoint-coverage/endpoint-coverage-report.md` | Output sink for the human-readable endpoint coverage report. |
| `artifacts/model-audit/` | Output sink for `inventory.json`, `matrix.json`, `report.md`, and optional probe/build/baseline audit artifacts. |

## Notes
- `src/nbadb/docs_gen/lineage.py` builds two complementary inventories: schema lineage from Pandera metadata and SQL lineage from discovered `SqlTransformer` subclasses parsed with SQLGlot.
- `LineageGenerator._collect_lineage_data()` splits lineage into extraction-layer and transform-layer Mermaid graphs; `write()` emits `lineage-auto.mdx` and `lineage.json` together.
- `src/nbadb/core/transform_dependency_graph.py` is the cleanest raw source for dependency kind (`transform_output`, `staging`, `raw`, `unresolved`), consumer relationships, cycle detection, and topological execution order. It complements the docs lineage generator rather than replacing it.
- `src/nbadb/core/endpoint_coverage.py` is the ownership and gap taxonomy source for `covered`, `runtime_gap`, `staging_only`, `extractor_only`, and `source_only`, plus the `star_schema_coverage` payload used to measure schema-backed docs coverage.
- `src/nbadb/core/model_audit.py` pulls `LineageGenerator().generate_dict()` into the audit inventory and records `schema_lineage_present` and `sql_lineage_present` for each runtime transform output. It is the strongest single join point between lineage evidence and model-ownership decisions.
- Current generated docs coverage snapshot in `docs/lib/generated/schema-coverage.json`: 184 lineage outputs, 118 schema tables, and 66 transform outputs missing schema-backed reference coverage.
- `docs/components/site/docs-generated-coverage.tsx` is the docs presentation layer for that gap. It explicitly frames lineage coverage as broader than schema-reference coverage and points readers back to `docs/lib/generated/schema-coverage.json`.
- `docs/content/docs/start/architecture.mdx` and `docs/content/docs/ops/troubleshooting.mdx` both treat `lineage-auto.mdx`, `docs/lib/generated/lineage.json`, and `docs/lib/generated/schema-coverage.json` as generator-owned outputs refreshed by `uv run nbadb docs-autogen --docs-root docs/content/docs`.

## Planned wiki coverage
- `wiki/model/lineage-wayfinding.md`
- `wiki/model/endpoint-coverage.md`
- `wiki/topics/model-audit.md`
- `wiki/topics/docs-autogen.md`

## Provenance
- `src/nbadb/docs_gen/lineage.py`
- `src/nbadb/core/transform_dependency_graph.py`
- `src/nbadb/core/endpoint_coverage.py`
- `src/nbadb/core/model_audit.py`
- `docs/content/docs/model/lineage/index.mdx`
- `docs/content/docs/model/lineage/table-lineage.mdx`
- `docs/content/docs/model/lineage/column-lineage.mdx`
- `docs/content/docs/lineage/lineage-auto.mdx`
- `docs/content/docs/model/lineage/meta.json`
- `docs/lib/generated/lineage.json`
- `docs/lib/generated/schema-coverage.json`
- `docs/components/site/docs-generated-coverage.tsx`
- `docs/content/docs/start/architecture.mdx`
- `docs/content/docs/ops/troubleshooting.mdx`
