# Docs Generator Manifest

## Purpose
- Grouped internal extract for the `docs-autogen` command, generator-owned docs artifacts, generated machine data, and the optional profiling JSON contract.

## High-value paths

### Command and path resolution
| Path | Inventory role |
| --- | --- |
| `src/nbadb/cli/commands/docs_autogen.py` | User-facing CLI wrapper that runs the docs generator and reports `updated:` / `unchanged:` outputs. |
| `src/nbadb/docs_gen/autogen.py` | Canonical output-path resolver and orchestration entrypoint for schema, dictionary, diagrams, lineage, generated JSON, site metrics, and optional profiling JSON. |
| `docs/AGENTS.md` | Docs ownership boundary: authored docs stay hand-edited, generator-owned outputs are refreshed from code. |

### Generator modules
| Path | Inventory role |
| --- | --- |
| `src/nbadb/docs_gen/schema_docs.py` | Generates schema-reference JSON and MDX stubs. |
| `src/nbadb/docs_gen/data_dictionary.py` | Generates data-dictionary JSON and MDX stubs. |
| `src/nbadb/docs_gen/er_diagram.py` | Generates ER diagram MDX and schema JSON payloads. |
| `src/nbadb/docs_gen/lineage.py` | Generates lineage MDX and machine-readable lineage payloads. |
| `src/nbadb/docs_gen/site_metrics.py` | Generates the docs-site metrics module. |
| `src/nbadb/docs_gen/table_profile.py` | Generates the optional table-profile JSON artifact for the admin profiling page. |

### Output contracts
| Path | Inventory role |
| --- | --- |
| `docs/content/docs/model/schema/` | Current code-owned schema-reference output directory. |
| `docs/content/docs/model/dictionary/` | Current code-owned data-dictionary output directory. |
| `docs/content/docs/model/diagrams/` | Current code-owned diagrams output directory. |
| `docs/content/docs/model/lineage/` | Current code-owned lineage output directory. |
| `docs/lib/generated/` | Machine-readable docs JSON backing data. |
| `docs/table-profile.generated.json` | Optional profiling artifact written only when a local DuckDB file exists. |

## Notes
- The generator resolves output paths from `docs_root`; for the canonical root `docs/content/docs`, machine JSON lands in `docs/lib/generated/`.
- The table-profile artifact is command-owned but conditional. Missing `docs/table-profile.generated.json` is not a broken contract when no local DuckDB file is present.
- `docs-autogen` is the repair path for generator-owned docs drift; hand-edited public docs pages should not be rewritten into generated surfaces.

## Planned wiki coverage
- `wiki/topics/docs-autogen.md`
- `wiki/topics/docs-profiling-surface.md`
- `wiki/topics/docs-generator-internals.md`

## Provenance
- `docs/AGENTS.md`
- `src/nbadb/cli/commands/docs_autogen.py`
- `src/nbadb/docs_gen/autogen.py`
- `src/nbadb/docs_gen/schema_docs.py`
- `src/nbadb/docs_gen/data_dictionary.py`
- `src/nbadb/docs_gen/er_diagram.py`
- `src/nbadb/docs_gen/lineage.py`
- `src/nbadb/docs_gen/site_metrics.py`
- `src/nbadb/docs_gen/table_profile.py`
