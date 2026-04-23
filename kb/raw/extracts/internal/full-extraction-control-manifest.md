# Full Extraction Control Manifest

## Purpose
- Grouped internal extract for the manifest-driven `Full Extraction` workflow: support-matrix planning, lane generation, preflight validation, lane execution, merge, chaining, and live-snapshot append behavior.

## High-value paths

### Workflow control plane
| Path | Inventory role |
| --- | --- |
| `.github/workflows/full-extraction.yml` | Canonical end-to-end workflow: generate support matrix, build manifest, validate lanes, fan out extraction, merge lane artifacts, run transform-only backfill, append a live snapshot, and build a resume manifest when needed. |
| `.github/actions/nordvpn-connect/action.yml` | VPN setup used by active extraction lanes. |
| `.github/actions/nordvpn-disconnect/action.yml` | VPN cleanup used after non-resume lanes finish. |

### Manifest and lane controller
| Path | Inventory role |
| --- | --- |
| `src/nbadb/orchestrate/full_extraction_control.py` | Defines `FullExtractionLane`, `FullExtractionManifest`, validation rules, default lane construction, merge logic, and resume-manifest generation with quarantined VPN servers. |
| `src/nbadb/core/endpoint_coverage.py` | Supplies the support-matrix contract consumed by the controller. |
| `src/nbadb/cli/commands/endpoint_support_matrix.py` | CLI entrypoint that refreshes the support-matrix artifacts before planning. |

### Planner and journal seam
| Path | Inventory role |
| --- | --- |
| `src/nbadb/orchestrate/planning.py` | Historical planning semantics that the strict roadmap expects to converge with the lane controller. |
| `src/nbadb/orchestrate/journal.py` | Journal and watermark contract that resume, replay, and completeness reasoning depend on. |
| `src/nbadb/orchestrate/backfill.py` | Transform-only backfill path used after merged staging is ready. |

### Live append seam
| Path | Inventory role |
| --- | --- |
| `src/nbadb/cli/commands/live_snapshot.py` | Manual append command used directly in the workflow after merge and transform. |
| `src/nbadb/orchestrate/live_snapshot.py` | Append-only live snapshot warehouse implementation. |

## Notes
- The workflow is no longer just static year shards. It plans lanes from fresh support-matrix artifacts, validates them, records per-lane metadata, merges lane databases, and then decides whether another chained iteration is needed.
- `resume_only` is a first-class lane state. Resume-only lanes restore cached DuckDB state, skip VPN bootstrap, and exist to continue incomplete work rather than restart it.
- Chaining carries `chain_state.vpn_quarantined_servers` forward so repeated bad VPN exits can be excluded from the next iteration.
- A successful merge iteration ends with `uv run nbadb backfill run --transform-only --verbose` and then `uv run nbadb live-snapshot --verbose`.

## Planned wiki coverage
- `wiki/topics/full-extraction-control-plane.md`
- `wiki/topics/live-snapshot-contract.md`
- `wiki/topics/strict-source-complete-roadmap.md`

## Provenance
- `.github/workflows/full-extraction.yml`
- `.github/actions/nordvpn-connect/action.yml`
- `.github/actions/nordvpn-disconnect/action.yml`
- `src/nbadb/orchestrate/full_extraction_control.py`
- `src/nbadb/core/endpoint_coverage.py`
- `src/nbadb/cli/commands/endpoint_support_matrix.py`
- `src/nbadb/orchestrate/planning.py`
- `src/nbadb/orchestrate/journal.py`
- `src/nbadb/orchestrate/backfill.py`
- `src/nbadb/cli/commands/live_snapshot.py`
- `src/nbadb/orchestrate/live_snapshot.py`
