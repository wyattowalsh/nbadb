# Endpoint Coverage And Audit Manifest

## Purpose
- Grouped internal extract for the strict endpoint-support matrix, the broader endpoint-coverage taxonomy, and the stricter model-audit inventory surface.

## High-value paths

### Strict contract and coverage inventory
| Path | Inventory role |
| --- | --- |
| `src/nbadb/core/endpoint_coverage.py` | Canonical coverage taxonomy, support-matrix payload generation, execution-semantics classification, and star-schema coverage rollups. |
| `src/nbadb/cli/commands/endpoint_support_matrix.py` | User-facing strict-contract command that writes the support matrix artifacts and enforces `--require-complete` / `--require-season-type-contract`. |
| `artifacts/endpoint-coverage/endpoint-support-matrix.json` | Machine-readable per-surface support contract used by the full-extraction planner. |
| `artifacts/endpoint-coverage/endpoint-coverage-summary.json` | Machine-readable coverage summary and gap breakdown. |
| `artifacts/endpoint-coverage/endpoint-coverage-report.md` | Human-readable endpoint coverage narrative. |

### Stricter audit inventory
| Path | Inventory role |
| --- | --- |
| `src/nbadb/core/model_audit.py` | Higher-order audit engine that inventories runtime, staging, model, and column-origin gaps and writes the audit bundle. |
| `.github/baselines/model-audit-summary.json` | Current no-regressions baseline for the stricter audit surface. |
| `artifacts/model-audit/` | Output sink for `inventory.json`, `matrix.json`, `report.md`, and optional probe/build artifacts. |

### Workflow/control-plane bridge
| Path | Inventory role |
| --- | --- |
| `.github/workflows/full-extraction.yml` | Planning step that regenerates support-matrix artifacts before manifest construction. |
| `src/nbadb/orchestrate/full_extraction_control.py` | Controller that consumes the support-matrix payload to build runnable lanes. |

## Notes
- `endpoint_support_matrix` is the strict historical/live contract surface used by the full-extraction planner.
- `endpoint_coverage.py` and `model_audit.py` overlap, but they answer different questions: "what is supported and modeled?" versus "what still has runtime, schema, validation, or lineage debt?"
- The full-extraction workflow treats fresh support-matrix artifacts as a planning prerequisite rather than stale background documentation.

## Planned wiki coverage
- `wiki/topics/endpoint-coverage-source-summary.md`
- `wiki/topics/model-audit.md`
- `wiki/topics/full-extraction-control-plane.md`
- `wiki/topics/strict-source-complete-roadmap.md`

## Provenance
- `src/nbadb/core/endpoint_coverage.py`
- `src/nbadb/cli/commands/endpoint_support_matrix.py`
- `src/nbadb/core/model_audit.py`
- `.github/workflows/full-extraction.yml`
- `src/nbadb/orchestrate/full_extraction_control.py`
