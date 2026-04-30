---
title: Runbook Registry
tags:
  - kb
  - operations
  - runbooks
aliases:
  - Operational Procedures
  - Runbook Index
kind: index
status: active
updated: 2026-04-30
source_count: 7
---

# Runbook Registry

Central index for operational procedures. Use this page to find the exact runbook for your task.

## Daily Operations

- **[[run-modes|Run Modes]]** — Choose between `init`, `daily`, `monthly`, and `backfill run` based on your refresh scope
- **[[../routes/operator-route|Operator Route]]** — Game-day operations board: symptom chooser and recovery loop
- **`docs/content/docs/ops/daily-updates.mdx`** — Authored daily operations runbook in docs site

## Troubleshooting & Recovery

- **[[troubleshooting|Troubleshooting Playbook]]** — Film-room diagnostic guide; start with exact failing artifact or command
- **Fast triage commands**:
  ```bash
  uv run nbadb status --output-format json
  uv run nbadb scan --report-path artifacts/health/local/data-quality-report.json
  uv run nbadb extract-completeness
  ```

## Kaggle Management

- **[[kaggle-distribution|Kaggle Distribution]]** — Download (seed) and upload (publish) workflows
- **`docs/content/docs/ops/kaggle.mdx`** — Authored Kaggle delivery guide in docs site
- **Key commands**:
  ```bash
  uv run nbadb download                        # Seed local data dir from Kaggle
  uv run nbadb upload -m "message"             # Publish to Kaggle
  uv run nbadb metadata --output dataset-metadata.json  # Generate metadata
  ```

## Pipeline Maintenance

- **`kb/config/maintenance-triage.md`** — Vault maintenance decisions and escalation triggers (for KB stewards)
- **`kb/config/shard-governance.md`** — Migration and change management rules (for KB stewards)
- **`docs/content/docs/ops/troubleshooting.mdx`** — Authored troubleshooting guide in docs site

## Emergency Procedures

- **Graceful stop during pipeline commands**: first `Ctrl+C` is graceful (journal/checkpoint preserved), second forces exit
- **Rerun after interruption**: use `uv run nbadb daily`, `monthly`, or `backfill run` depending on scope
- **Live snapshot manual recovery**: `uv run nbadb live-snapshot` (used by `daily` and `monthly` automatically when games are active)

## Docs Artifact Regeneration

- **Auto-generated docs**:
  ```bash
  uv run nbadb docs-autogen --docs-root docs/content/docs
  ```
  Updates schema references, data dictionary, ER diagrams, and lineage automatically.

## Quick Operator Decision Tree

| Symptom | First check | Next step |
| --- | --- | --- |
| Normal freshness drift | `uv run nbadb status --output-format json` | `uv run nbadb daily` |
| Wider recent-history mismatch | `uv run nbadb status --output-format json` | `uv run nbadb monthly` |
| Known gaps or retries needed | `uv run nbadb backfill gaps --output-format json` | `uv run nbadb backfill run` |
| Empty/missing tables | `uv run nbadb scan --report-path artifacts/health/local/data-quality-report.json` | Rerun narrowest refresh |
| Coverage drift | `uv run nbadb extract-completeness` | Check extractor/staging map |
| Docs drifted | Run `docs-autogen` and compare output | Rebuild docs site after artifacts update |

## Runbook Locations Summary

| Type | Location | Format |
| --- | --- | --- |
| Internal KB runbooks | `kb/wiki/operations/` | Obsidian markdown with wikilinks |
| Authored public runbooks | `docs/content/docs/ops/` | MDX (Next.js components) |
| Maintenance/governance | `kb/config/` | Obsidian markdown |
| Role-based entry points | `kb/wiki/routes/` | Obsidian markdown |

## Provenance

| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| runbook registry | `kb/wiki/operations/runbooks.md` | central index (this file) |
| run mode selector | `kb/wiki/operations/run-modes.md` | internal KB |
| operator route | `kb/wiki/routes/operator-route.md` | internal KB |
| troubleshooting | `kb/wiki/operations/troubleshooting.md` | internal KB |
| kaggle operations | `kb/wiki/operations/kaggle-distribution.md` | internal KB |
| daily updates | `docs/content/docs/ops/daily-updates.mdx` | public authored |
| troubleshooting | `docs/content/docs/ops/troubleshooting.mdx` | public authored |
| kaggle guide | `docs/content/docs/ops/kaggle.mdx` | public authored |
| vault governance | `kb/config/maintenance-triage.md` | internal governance |
| public commands | `AGENTS.md` > Commands section | maintainer contract |

## Related Indexes

- [[../../indexes/fleet-lane-map|Fleet Lane Map]] — Lane ownership and handoff points
- [[../../../config/upkeep-standards|Upkeep Standards]] — Scheduled maintenance cadences
