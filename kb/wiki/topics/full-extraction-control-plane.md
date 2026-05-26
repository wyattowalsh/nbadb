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
updated: 2026-05-21
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
9. build the next chained manifest when resumable or blocked work remains

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

That lane metadata is what later lets the controller decide whether a non-complete lane should be resumed, skipped as a documented contract block, or failed as a pipeline problem.

The lane metadata status is one of four final outcomes:

| Outcome | Contract |
|---------|----------|
| `complete` | Extraction finished successfully. |
| `needs_resume` | The lane timed out or stopped after persisted DuckDB/journal progress and remains active in the next manifest. |
| `contract_blocked` | The endpoint/range is backed by support-rule evidence and is included in `extraction-audit.json`, but not retried. |
| `pipeline_failure` | Missing artifacts, VPN/auth failure, manifest/control-plane failure, unclassified extract error, or secret leakage; the workflow must fail red. |

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
- keep `needs_resume` lanes active
- skip `contract_blocked` lanes while counting them in the summary
- carry failure streaks forward
- quarantine VPN servers in `chain_state.vpn_quarantined_servers`
- emit summary counts such as active-lane, resume-only-lane, contract-blocked-lane, split-lane, and outcome counts

The result is a chain-aware workflow instead of a fixed one-shot shard list.

For repeated game/date timeouts, the controller splits resumable children down to one-season lanes so the next chain iteration narrows the retry surface without discarding parent lane cache/journal state.

## Practical maintainer rules
- Treat the support matrix as the planning input, not as docs-only reporting.
- Treat `FullExtractionLane` as the atomic execution unit.
- Treat merge plus transform-only backfill as the point where staged lane work becomes one coherent warehouse state.
- Treat chained manifests as the source of truth for what the next iteration should do.
- Add support rules in `src/nbadb/orchestrate/extraction_contract.py`, not as scattered workflow or script exceptions.
- Add historical box-score support rules only after lane metadata or a targeted probe confirms a zero-row, all-call failure floor or range. Runs `26276583988` and `26385964741` established these contract gaps:
  - `box_score_advanced`: 1946-1995
  - `box_score_defensive`: 1946-2015
  - `box_score_four_factors`: 1946-1995
  - `box_score_matchups`: 1946-2013
  - `box_score_misc`: 1946-1993
  - `box_score_player_track`: 1946-1993
  - `box_score_scoring`: 1946-1993

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
