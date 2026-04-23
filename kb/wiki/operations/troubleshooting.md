---
title: Troubleshooting
tags:
  - kb
  - operations
  - troubleshooting
aliases:
  - Troubleshooting Playbook
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Troubleshooting

Do not widen to a full rebuild by default. Start from the exact failing command, artifact, or report, fix the local cause, then rerun the narrowest command that proves the fix.

## Fast triage commands
```bash
uv run nbadb status --output-format json
uv run nbadb scan --report-path artifacts/health/local/data-quality-report.json
uv run nbadb backfill gaps --output-format json
uv run nbadb extract-completeness
uv run nbadb docs-autogen --docs-root docs/content/docs
```

## Symptom table
| Symptom | First check | Likely next move |
| --- | --- | --- |
| database not found | confirm `data_dir` and presence of DuckDB/SQLite artifacts | run `init` or `download` |
| recent data looks stale | check `status` and recent run mode used | escalate from `daily` to `monthly` or `backfill run` |
| empty or missing tables | run `scan` and inspect the JSON report | rerun the narrowest matching refresh command |
| coverage drift | run `extract-completeness` | check extractor/staging map ownership |
| generated docs drifted | run `docs-autogen` from repo root | rebuild docs after generator output is current |

## Known drift to remember
- Some project instructions still mention `nbadb run-quality`, but the live CLI surface uses `nbadb scan`.
- Authored docs and checked-in config disagree on the default `data_dir`.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| public troubleshooting framing | `README.md` | public command pointers |
| maintainer gotchas | `AGENTS.md` | repo operating rules |
| troubleshooting playbook | `docs/content/docs/ops/troubleshooting.mdx` | primary authored runbook |
| recurring refresh context | `docs/content/docs/ops/daily-updates.mdx` | operator route |
| CLI command route | `docs/content/docs/start/cli-reference.mdx` | command reference |
| path/default caveats | `src/nbadb/core/config.py` | settings behavior |
| Kaggle client behavior | `src/nbadb/kaggle/client.py` | distribution troubleshooting context |
| companion route note | `wiki/operations/run-modes.md` | internal KB cross-link |
