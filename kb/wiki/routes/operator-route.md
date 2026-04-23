---
title: Operator Route
tags:
  - kb
  - routes
  - operations
aliases:
  - Refresh Route
kind: overview
status: active
updated: 2026-04-16
source_count: 3
---

# Operator Route

Use this route when the job is freshness, reruns, gap-filling, artifact checks, or recovery.

## First possession
```bash
uv run nbadb status --output-format json
```

## Symptom chooser
| If the symptom is... | Start with |
| --- | --- |
| Normal recurring freshness drift | `uv run nbadb daily` |
| Wider recent-history mismatch | `uv run nbadb monthly` |
| Missing runs, retries, or known gaps | `uv run nbadb backfill run` |
| The warehouse looks fine but the answer still seems wrong | [[analyst-route|Analyst Route]] |

Then choose the narrowest refresh that fits the symptom:

| Command | Use it when |
| --- | --- |
| `uv run nbadb daily` | Normal recurring refresh |
| `uv run nbadb monthly` | Wider recent-history sweep |
| `uv run nbadb backfill run` | Recovery, retry, or targeted gap fill |

> [!tip]
> Start narrow. Escalate only when the narrower lane cannot clear the issue.

## Default recovery loop
- Check state with `uv run nbadb status --output-format json`
- Check quality with `uv run nbadb scan --report-path artifacts/health/local/data-quality-report.json`
- Check coverage with `uv run nbadb extract-completeness`
- Regenerate generated docs with `uv run nbadb docs-autogen --docs-root docs/content/docs` when docs drift is part of the failure

## Watch for
- `daily` is the default half-court set.
- First `Ctrl+C` is graceful; second forces exit.
- Internal `_pipeline_*` tables track operational state and are not public analytics surfaces.
- Inspect the artifact or JSON report, not just terminal output.

## Open next
- [[../operations/run-modes|Run Modes]]
- [[../operations/troubleshooting|Troubleshooting]]
- [[../operations/kaggle-distribution|Kaggle Distribution]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| operator route framing | `docs/content/docs/start/onboarding.mdx` | role-based onboarding |
| recurring refresh workflow | `docs/content/docs/ops/daily-updates.mdx` | runbook lane |
| recovery loop | `docs/content/docs/ops/troubleshooting.mdx` | troubleshooting lane |
