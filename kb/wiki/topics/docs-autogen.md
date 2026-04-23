---
title: Docs Autogen
tags:
  - kb
  - topics
  - docs
  - generation
aliases:
  - docs-autogen Command
kind: concept
status: active
updated: 2026-04-22
source_count: 8
---

# Docs Autogen

Use this note when a docs-visible change might belong to the generator lane instead of a hand-edited MDX page.

## Command
`uv run nbadb docs-autogen --docs-root docs/content/docs`

Run it from the repo root, not from `docs/`.

## What the command owns
| Artifact lane | Outputs |
| --- | --- |
| Schema reference outputs | `docs/content/docs/model/schema/` |
| Data dictionary outputs | `docs/content/docs/model/dictionary/` |
| Generated diagrams and lineage | `docs/content/docs/model/diagrams/`, `docs/content/docs/model/lineage/` |
| Machine-readable docs data | `docs/lib/generated/*.json` including `schema.json`, `lineage.json`, and `schema-coverage.json` |
| Homepage metrics module | `docs/lib/site-metrics.generated.ts` |
| Optional profiling artifact | `docs/table-profile.generated.json` when a local DuckDB file exists |

## Working rules
- Hand-edit authored docs pages. Regenerate generator-owned artifacts.
- The command writes deterministically and reports `updated:` or `unchanged:` per artifact.
- With the default docs root, machine JSON lands under `docs/lib/generated/`.
- `lineage-auto.mdx` gets a coverage note derived from lineage outputs vs schema-backed outputs.
- Site metrics are regenerated from live repo discovery, not copied from docs prose.
- `docs/table-profile.generated.json` is optional and only appears when the local DuckDB database exists.

## When to reach for it
- schema classes changed
- transform outputs or lineage changed
- docs-side scoreboard metrics drifted
- generated reference pages are stale after code changes

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/model/schema-wayfinding|Schema Wayfinding]]
- [[wiki/model/lineage-wayfinding|Lineage Wayfinding]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| public command summary | `README.md` | command appears in repo-facing CLI surface |
| authored vs generated docs boundary | `AGENTS.md` | repo-level docs workflow |
| docs-root warning and generator-owned pages | `docs/AGENTS.md` | docs app operating rules |
| CLI command behavior and console output | `src/nbadb/cli/commands/docs_autogen.py` | exact command implementation |
| generated artifact list and path rules | `src/nbadb/docs_gen/autogen.py` | generator entrypoint |
| grouped docs-generator bridge | `raw/extracts/internal/docs-generator-manifest.md` | KB bridge for docs generator ownership and optional profiling output |
| optional profiling artifact generator | `src/nbadb/docs_gen/table_profile.py` | profiling JSON contract |
| site metrics generation | `src/nbadb/docs_gen/site_metrics.py` | generated scoreboard module |
