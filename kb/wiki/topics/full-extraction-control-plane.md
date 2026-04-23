---
title: Full Extraction Control Plane
tags:
  - kb
  - topics
  - extraction
  - workflow
  - control-plane
aliases:
  - Full Extraction Workflow Control Plane
  - Manifest-Driven Full Extraction
kind: concept
status: active
updated: 2026-04-22
source_count: 8
---

# Full Extraction Control Plane

Use this note when the question is "how does `Full Extraction` actually move from a strict support matrix to runnable lanes, merged staging, and chained resume iterations?"

## At a glance
The current control flow is:

1. regenerate strict support-matrix artifacts
2. build a manifest from that support matrix
3. validate and preflight the manifest
4. fan out one workflow matrix row per lane
5. save lane metadata and lane-local DuckDB state
6. merge successful lane databases
7. run transform-only backfill on the merged staging state
8. append a live snapshot
9. build the next chained manifest when incomplete or blocked work remains

## 1. Plan from the support matrix
The workflow starts by regenerating `artifacts/endpoint-coverage/endpoint-support-matrix.json` with `uv run nbadb endpoint-support-matrix`.

That artifact is the planning contract. `src/nbadb/orchestrate/full_extraction_control.py` reads it, filters to runnable rows, groups historical surfaces by pattern and supported season-type set, and emits `FullExtractionLane` entries with:
- `lane_id`
- `lane_kind`
- `season_start` / `season_end`
- `patterns`
- `season_types`
- `endpoints`
- `use_vpn`
- `resume_only`
- `timeout_seconds`

The support matrix therefore decides what can be planned; the workflow YAML just executes the plan.

## 2. Preflight before fanout
The workflow validates the generated manifest before any extraction lane runs.

The controller rejects invalid lane shapes such as:
- one-sided season ranges
- non-positive timeouts
- negative failure streaks
- active lanes without VPN
- spans that exceed the per-pattern lane policy

This is the point of the manifest layer: lane policy is encoded in Python and checked once up front instead of scattered across shell/YAML branches.

## 3. Lane matrix execution
Each lane becomes one workflow matrix row.

Operationally important lane behavior:
- active lanes require VPN bootstrap
- `resume_only` lanes skip VPN setup and assume cached DuckDB state is the recovery surface
- lane metadata is written as a per-lane workflow artifact
- lane DuckDB files are cached and uploaded as artifacts keyed by chain id, lane id, and iteration

That lane metadata is what later lets the controller decide whether a failed lane should be replayed, resumed, or quarantined.

## 4. Merge, transform, and append
Once all planned lanes for an iteration succeed, the workflow merges the lane databases with:

```bash
uv run python -m nbadb.orchestrate.full_extraction_control merge --artifacts-dir lanes --output-dir data/nbadb
```

After merge, the workflow runs:

```bash
uv run nbadb backfill run --transform-only --verbose
uv run nbadb live-snapshot --verbose
```

That split matters:
- lane execution fills staging state
- merge combines the lane-local staging databases
- transform-only backfill builds the modeled warehouse from merged staging
- the live snapshot append is a final append-only upkeep step, not part of historical lane replay

## 5. Chaining and resume semantics
The workflow does not reason only from shell exit codes. It also builds a follow-up manifest from lane metadata.

`build_resume_manifest(...)` can:
- mark specific lanes `resume_only`
- carry failure streaks forward
- quarantine VPN servers in `chain_state.vpn_quarantined_servers`
- emit summary counts such as active-lane count and resume-only-lane count

The result is a chain-aware workflow instead of a fixed one-shot shard list.

## Practical maintainer rules
- Treat the support matrix as the planning input, not as docs-only reporting.
- Treat `FullExtractionLane` as the atomic execution unit.
- Treat merge plus transform-only backfill as the point where staged lane work becomes one coherent warehouse state.
- Treat chained manifests as the source of truth for what the next iteration should do.

## Related notes
- [[wiki/topics/strict-source-complete-roadmap|Strict Source-Complete Roadmap]]
- [[wiki/topics/endpoint-coverage-source-summary|Endpoint Coverage Source Summary]]
- [[wiki/topics/model-audit|Model Audit]]
- [[wiki/topics/live-snapshot-contract|Live Snapshot Contract]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| workflow sequence from planning through merge and chained resume | `.github/workflows/full-extraction.yml` | canonical CI control plane |
| lane and manifest data model, validation rules, merge logic, and chained resume builder | `src/nbadb/orchestrate/full_extraction_control.py` | canonical controller implementation |
| support-matrix generation and strict command contract | `src/nbadb/cli/commands/endpoint_support_matrix.py` | strict planning entrypoint |
| support-matrix taxonomy and runnable-surface classification | `src/nbadb/core/endpoint_coverage.py` | planning vocabulary source |
| planner and workload-completeness seam | `src/nbadb/orchestrate/planning.py` | historical workload model |
| journal/replay semantics | `src/nbadb/orchestrate/journal.py` | resume and replay contract |
| transform-only merge follow-up | `src/nbadb/orchestrate/backfill.py` | post-merge transform surface |
| grouped workflow/control evidence | `raw/extracts/internal/full-extraction-control-manifest.md` | KB bridge for this control-plane note |
