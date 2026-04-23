---
title: Live Snapshot Contract
tags:
  - kb
  - topics
  - live
  - snapshots
  - operations
aliases:
  - Live Snapshot Semantics
  - Append-Only Live Snapshot Contract
kind: concept
status: active
updated: 2026-04-22
source_count: 7
---

# Live Snapshot Contract

Use this note when the question is "what is the intended split between `daily`, `monthly`, and `live-snapshot`, and how are live surfaces warehoused?"

## Short version
- `daily` and `monthly` already append live snapshots when active games exist.
- `live-snapshot` is the manual recovery and debugging command.
- live warehousing is append-only; it is not historical backfill.

## Automatic upkeep path
The repo-level contract is explicit:
- `nbadb daily` = current-season refresh plus automatic live snapshot append when games are active
- `nbadb monthly` = recent-season refresh plus automatic live snapshot append when games are active
- `nbadb live-snapshot` = manual append for active games or explicit game ids

`PipelineOrchestrator` implements that split through `_run_live_snapshot_upkeep(...)`, which is called at the end of `daily()` and `monthly()`.

That means automatic live upkeep belongs to the normal operator refresh paths already; it is not a missing feature waiting on the manual command.

## Manual command surface
`uv run nbadb live-snapshot` is the explicit operator tool for:
- recovering after a failed or interrupted automatic append
- forcing snapshots for explicit `--game-id` values
- debugging live ingestion with a manual `--snapshot-at` timestamp

If no live games are active and no explicit game ids are supplied, the command exits cleanly with a no-active-games message.

## Warehouse semantics
`LiveSnapshotWarehouse` is intentionally separate from the historical journal and replace-style transform flow.

The important contract points are:
- `load_mode` is append-only and rejects anything else
- active games are discovered from the live scoreboard, filtered to `game_status == 2`
- raw and staging live frames are schema-validated before persistence
- staging persistence uses append semantics rather than overwrite semantics
- discovered live transformers load star outputs from that append-only staging state

Repeated snapshots for the same game are therefore expected to coexist side by side.

## Relationship to full extraction
The full-extraction workflow appends a live snapshot only after:
1. lane extraction finishes
2. lane databases merge
3. transform-only backfill rebuilds the modeled warehouse

That ordering keeps live snapshot behavior separate from historical completeness claims. Historical lanes fill the backfill contract; the live snapshot append is current-state upkeep layered on top.

## Practical maintainer rules
- Do not describe `live-snapshot` as the normal live-ingestion path; it is the manual recovery/debugging seam.
- Do not describe live endpoints as historical backfill surfaces.
- Do not treat missing live snapshots as evidence that `daily` or `monthly` lack live support; check whether active games existed and whether the upkeep step ran.

## Related notes
- [[wiki/operations/run-modes|Run Modes]]
- [[wiki/topics/full-extraction-control-plane|Full Extraction Control Plane]]
- [[wiki/topics/strict-source-complete-roadmap|Strict Source-Complete Roadmap]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| public run-mode contract for `daily`, `monthly`, and `live-snapshot` | `README.md` | public command framing |
| maintainer-facing live snapshot contract | `AGENTS.md` | explicit maintainer rule |
| manual live-snapshot CLI behavior, `--game-id`, and `--snapshot-at` | `src/nbadb/cli/commands/live_snapshot.py` | canonical manual command |
| append-only live warehouse semantics and active-game discovery | `src/nbadb/orchestrate/live_snapshot.py` | canonical live snapshot implementation |
| automatic upkeep inside `daily` and `monthly` | `src/nbadb/orchestrate/orchestrator.py` | orchestrator upkeep path |
| full-extraction post-merge live append step | `.github/workflows/full-extraction.yml` | workflow-level upkeep path |
| grouped workflow/live evidence | `raw/extracts/internal/full-extraction-control-manifest.md` | KB bridge for the control-plane and live contract notes |
