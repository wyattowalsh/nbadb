---
title: Strict Source-Complete Roadmap
tags:
  - kb
  - topics
  - roadmap
  - extraction
  - model
aliases:
  - Strict Scratch-From-Zero Roadmap
  - Full Extraction Modernization Roadmap
kind: concept
status: active
updated: 2026-04-22
source_count: 8
---

# Strict Source-Complete Roadmap

Use this note when the question is: "what is the complete repo-grounded plan to get `nbadb` from the current partially-modeled support matrix to a true scratch-from-zero, endpoint-complete historical build plus first-class live snapshots?"

## Goal

Finish the platform so that:

1. every `nba_api` stats and static surface that is historically extractable is extracted from its earliest supported season or date
2. every supported season type is explicitly represented in the extraction contract
3. every in-scope surface is staged, transform-owned, schema-backed, and validation-covered
4. live endpoints are warehouse-modeled as append-only snapshot surfaces rather than mislabeled as historical backfills
5. `Full Extraction` becomes manifest-driven, resumable, and lane-based on free GitHub runners

## Current baseline

These counts come from the strict contract surfaces now present in the repo.

### Endpoint support baseline

From `uv run nbadb endpoint-support-matrix` on 2026-04-17:

| Metric | Value |
| --- | --- |
| endpoints | `136` |
| complete | `6` |
| partial | `6` |
| gaps | `124` |
| season-type-untracked | `57` |
| historical_backfill | `125` |
| reference_snapshot | `7` |
| live_snapshot | `4` |

Largest strict-contract gap buckets:

| Gap | Count |
| --- | --- |
| `input_schema_missing` | `102` |
| `output_schema_missing` | `87` |
| `transform_contract_missing` | `8` |
| `model_excluded` | `7` |
| `runtime_gap` | `6` |
| `snapshot_staging_missing` | `4` |
| `snapshot_transform_missing` | `4` |

### Model audit baseline

From the current inventory audit and repo baselines:

| Metric | Value |
| --- | --- |
| problem_count | `2052` |
| schema_gap | `66` |
| input_schema_missing | `277` |
| column_origin_missing | `1698` |
| live_surface_unmodeled | `4` |

### Workflow reality

The current `Full Extraction` flow is still:

- fixed-shard, year-bucketed YAML fanout in `.github/workflows/full-extraction.yml`
- repeated per-shard discovery and per-shard VPN/bootstrap overhead
- merge behavior that assumes a special base shard
- chain-on-failure behavior that reasons from shard exit codes, not manifest completeness

## Success contract

The program is done only when all of these are true:

| Area | Done means |
| --- | --- |
| historical stats/static | every historically extractable surface is extracted from its earliest supported season/date |
| season types | every in-scope historical surface has explicit season-type capability metadata |
| staging | every in-scope surface has extractor coverage, runtime/source coverage, and input-schema coverage |
| transforms | every in-scope staging surface is transform-owned or explicitly accepted as a non-modeled exception |
| star schemas | every intended output has a registered star schema |
| validation | modeled columns carry usable lineage/origin metadata and pass audit |
| live | all four live surfaces are append-only snapshot facts, not historical claims |
| workflow | `Full Extraction` is manifest-driven, resumable, and lane-based |

## Programs and critical path

There are six remaining slices, but only three are on the critical path.

### Critical path

1. explicit season-type contract
2. planner and journal completeness at season-type grain
3. manifest/controller/workflow redesign

### Parallel programs

1. model and schema closure
2. live snapshot warehousing

## Slice map

| Slice | Theme | Why it exists | Blocks |
| --- | --- | --- | --- |
| Slice 1 | Season-type contract | replaces inferred season-type status with explicit metadata | Slice 2, Slice 3 |
| Slice 2 | Planner and completeness math | counts real work units instead of season-only approximations | Slice 3 |
| Slice 3 | Manifest/controller/workflow | replaces shard-first YAML with lane-based execution | final canary |
| Slice 4 | Model closure | burns down transform/schema/input-schema/column-origin debt | final gates |
| Slice 5 | Live snapshots | turns live endpoints into real warehouse contracts | final gates |
| Slice 6 | CI and hard gates | converts the contract into enforceable checks | final |

## Subagent-optimized topology

Use one coordinator plus specialized subagents per slice. The point is to keep the big parallel program parallel without mixing unrelated files.

| Team | Assignment | Main files |
| --- | --- | --- |
| Team 1 | Slice 1 — season-type contract | `staging_map.py`, `endpoint_coverage.py`, contract tests |
| Team 2 | Slice 2 — planner/journal/backfill completeness | `planning.py`, `journal.py`, `backfill.py`, discovery tests |
| Team 3 | Slice 3 — manifest/controller/workflow | `.github/workflows/full-extraction.yml`, `orchestrator.py`, controller helper, NordVPN actions |
| Team 4A | Slice 4A — registry/artifact truth | `schemas/registry.py`, coverage artifacts, docs artifacts |
| Team 4B-1 | Slice 4B — game/boxscore/scoreboard schema batch | `schemas/star/*`, matching `transform/facts/*` |
| Team 4B-2 | Slice 4B — player dashboard detail batch | dashboard schemas and transforms |
| Team 4B-3 | Slice 4B — league/team/player seasonal fact batch | seasonal fact schemas and transforms |
| Team 4B-4 | Slice 4B — misc/draft/franchise/history batch | remaining fact schemas and transforms |
| Team 4C | Slice 4C — input-schema coverage | `schemas/staging/*`, `schemas/raw/*`, aliases |
| Team 4D | Slice 4D — column-origin metadata | star schemas and mixins |
| Team 5 | Slice 5 — live snapshots | `extract/live/endpoints.py`, live schemas, live transforms, orchestration |
| Team 6 | Slice 6 — CI/docs/canary | workflows, baselines, docs, hard gates |
| Team R | reviewer wave | review and risk-check after each execution wave |

## Wave plan

### Wave A

Run in parallel:

- Slice 1 — explicit season-type contract
- Slice 4A — registry and artifact truth cleanup
- Slice 5A — live snapshot contract and append/load design

Why first: this creates the real planning vocabulary and cleans the inventory surface before heavier work starts.

### Wave B

Run after Slice 1 stabilizes:

- Slice 2 — planner and journal completeness at season-type grain
- Slice 4B family batches in parallel

Why second: planner math must understand the contract before the workflow can reason about completeness correctly.

### Wave C

Run after Slice 2 stabilizes:

- Slice 3 — manifest/controller/workflow redesign

Why third: the workflow should depend on support-matrix + planner truth, not the other way around.

### Wave D

Run in parallel:

- Slice 5B-D — live snapshot implementation
- Slice 4C — input-schema closure
- Slice 4D — column-origin closure

Why fourth: once the controller path exists, the repo can safely absorb live and validation closure work without further redesigning the execution model.

### Wave E

Run last:

- Slice 6 — CI gates, docs, and full scratch-from-zero canaries

Why last: hard gates should only be turned on once the contract is actually achievable.

## Detailed slices

## Slice 1 — Explicit season-type contract

### Purpose

Replace the current inferred `season_type_contract_status="untracked"` behavior with explicit metadata on historical surfaces.

### Main files

- `src/nbadb/orchestrate/staging_map.py`
- `src/nbadb/core/endpoint_coverage.py`
- `tests/unit/core/test_endpoint_coverage.py`

### Main change

Add an explicit field on historical staging entries, for example:

- `per_request`
- `derived`
- `not_supported`
- `not_applicable`

### Acceptance criteria

- support matrix no longer infers season-type state from `param_pattern`
- every historical surface has explicit season-type capability metadata
- the support summary can distinguish true blockers from unimplemented but planned historical surfaces

### Primary risk

`player_team_season` likely cannot be treated as fully supported yet and should be marked explicit blocker first.

## Slice 2 — Planner and completeness math

### Purpose

Make the planner, journal, and backfill gap logic count work at the same grain the contract uses.

### Main files

- `src/nbadb/orchestrate/planning.py`
- `src/nbadb/orchestrate/journal.py`
- `src/nbadb/orchestrate/backfill.py`
- `tests/unit/orchestrate/test_planning.py`
- `tests/unit/orchestrate/test_backfill.py`

### Main change

Historical surfaces with `per_request` season-type semantics must plan and count `(season, season_type)` units rather than just `season`.

### Acceptance criteria

- `season`, `player_season`, and `team_season` fan out over explicit season types when the contract says they should
- journal counts distinguish regular season from playoffs and other supported types
- backfill completeness stops overstating done work

### Primary risk

Once this becomes correct, task counts will jump. That is expected and should be budgeted for.

## Slice 3 — Manifest/controller/workflow redesign

### Purpose

Replace the fixed year-bucket shards with a controller that only runs unresolved manifest units.

### Main files

- `.github/workflows/full-extraction.yml`
- `.github/actions/nordvpn-connect/action.yml`
- `.github/actions/nordvpn-disconnect/action.yml`
- `src/nbadb/orchestrate/orchestrator.py`
- `src/nbadb/orchestrate/planning.py`
- `src/nbadb/orchestrate/backfill.py`
- `src/nbadb/orchestrate/full_extraction_control.py`

### Main change

Move from:

- fixed shard matrix
- repeated per-shard discovery
- chain-by-exit-code

to:

- support-matrix seeded manifest
- discovery-resolved workload manifest
- lane-based execution
- retry only unresolved lanes
- merge once at the end

### Acceptance criteria

- no lane reruns completed work
- VPN is used only on extraction workers
- lane selection is driven by real support windows and contract semantics
- merge no longer depends on a special base shard

### Primary risk

The controller is the most architecture-heavy slice. Keep it small and explicit.

## Slice 4 — Model closure program

### Purpose

Burn down the warehouse debt that keeps the support matrix and audit in a gap state.

### Slice 4A — registry and artifact truth

Fix registry drift and stale schema-only artifacts so counts are trustworthy.

### Slice 4B — missing fact star schemas

Break into family batches:

1. game, box score, scoreboard, and game context
2. player dashboard and split details
3. league, team, and player seasonal facts
4. misc, draft, combine, franchise, and history facts

### Slice 4C — input-schema coverage

Add missing staging and raw schema coverage for transform-owned inputs.

### Slice 4D — column-origin metadata

Backfill origin metadata and validation coverage across existing schema-backed outputs.

### Acceptance criteria

- `schema_gap` trends toward zero
- `input_schema_missing` trends toward zero
- `column_origin_missing` trends toward zero
- support matrix `output_schema_missing` and `input_schema_missing` counts fall in sync with the audit

### Primary risk

This is the largest work program. It must stay family-batched or it will sprawl.

## Slice 5 — Live snapshot program

### Purpose

Turn the four live surfaces into real warehouse snapshot facts.

### Main files

- `src/nbadb/extract/live/endpoints.py`
- `src/nbadb/extract/base.py`
- live staging registry or `staging_map.py`
- live transforms and star schemas
- `src/nbadb/orchestrate/orchestrator.py`
- `src/nbadb/core/model_audit.py`

### Main change

Add append-only raw, staging, and star contracts for:

- `live_score_board`
- `live_odds`
- `live_play_by_play`
- `live_box_score`

Required snapshot metadata everywhere:

- `snapshot_at`
- `snapshot_date`
- `source_endpoint`
- natural grain keys like `game_id`

### Acceptance criteria

- support matrix no longer reports `snapshot_staging_missing`
- support matrix no longer reports `snapshot_transform_missing`
- model audit no longer reports `live_surface_unmodeled`
- live loads are append-only and separate from historical replace flows

### Primary risk

Load semantics. Live snapshot append behavior must not collide with historical replacement behavior.

## Slice 6 — CI, docs, and hard gates

### Purpose

Turn the now-explicit contract into enforcement.

### Main files

- `.github/workflows/ci.yml`
- audit/completeness workflows
- docs and generated artifacts

### Main change

Turn on gates in order:

1. soft informational reporting
2. no-regression support-matrix and audit baselines
3. strict completeness gates
4. scratch-from-zero canary
5. live snapshot canary

### Acceptance criteria

- regressions fail fast
- docs and generated artifacts reflect the final contract
- there is a reproducible scratch-from-zero canary path from an empty database and journal

### Primary risk

Turning on hard gates too early will produce noise instead of confidence.

## Dependency rules

| If this slice is incomplete | Do not treat these as done |
| --- | --- |
| Slice 1 | season-type completeness, strict historical planning |
| Slice 2 | manifest completeness, retry correctness |
| Slice 3 | full-extraction modernization |
| Slice 4 | endpoint-complete support matrix |
| Slice 5 | live completeness |
| Slice 6 | strict CI enforcement |

## Decision rules

When execution starts, use these rules:

- prefer shrinking ambiguity before adding throughput
- prefer family-batched schema/model work over broad cross-repo edits
- treat `model_excluded` as a real product decision, not a technical convenience
- keep live snapshot semantics separate from historical completeness semantics
- do not let workflow redesign race ahead of contract truth

## Recommended next execution wave

If execution starts from this roadmap, the first wave should be:

1. Slice 1 — explicit season-type contract
2. Slice 4A — registry and artifact truth cleanup
3. Slice 5A — live snapshot contract plus append/load design

That gives the later planner and workflow work a solid contract to stand on.

## Freshness trigger

Update this roadmap when any of these change:

- support-matrix counts materially change
- `Full Extraction` workflow architecture changes
- season-type contract semantics change
- model audit baseline drops enough to retire or split a slice
- live snapshot surfaces gain staging or star ownership

## Related notes

- [[wiki/topics/model-audit|Model Audit]]
- [[wiki/topics/endpoint-coverage-source-summary|Endpoint Coverage Source Summary]]
- [[wiki/topics/extractor-surface|Extractor Surface]]
- [[wiki/topics/season-time-semantics|Season Time Semantics]]
- [[wiki/operations/run-modes|Run Modes]]
- [[wiki/topics/full-extraction-control-plane|Full Extraction Control Plane]]
- [[wiki/topics/live-snapshot-contract|Live Snapshot Contract]]

## Provenance

| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| current support-matrix baseline and strict-contract vocabulary | `src/nbadb/core/endpoint_coverage.py`; local `uv run nbadb endpoint-support-matrix` output | canonical contract layer |
| model-audit baseline and gap categories | `src/nbadb/core/model_audit.py`; `.github/baselines/model-audit-summary.json`; `wiki/topics/model-audit.md` | stricter audit surface |
| historical support windows and staging execution contract | `src/nbadb/orchestrate/staging_map.py` | canonical historical support metadata surface |
| planner and backfill limitations | `src/nbadb/orchestrate/planning.py`; `src/nbadb/orchestrate/backfill.py`; `src/nbadb/orchestrate/journal.py`; `src/nbadb/orchestrate/discovery.py` | completeness math and workload-resolution constraints |
| current workflow design and NordVPN behavior | `.github/workflows/full-extraction.yml`; `.github/actions/nordvpn-connect/action.yml`; `.github/actions/nordvpn-disconnect/action.yml`; `src/nbadb/orchestrate/full_extraction_control.py` | current operational control plane |
| live extractor surface and current snapshot semantics | `src/nbadb/extract/live/endpoints.py`; `src/nbadb/extract/base.py`; `src/nbadb/core/model_audit.py` | current live boundary |
| repo architecture and public contract framing | `README.md`; `AGENTS.md`; `docs/content/docs/start/architecture.mdx` | project-level framing |
| grouped workflow/control bridge | `raw/extracts/internal/full-extraction-control-manifest.md` | KB bridge for manifest, merge, chaining, and live append behavior |
