---
title: Run Modes
tags:
  - kb
  - operations
  - pipeline
aliases:
  - Pipeline Run Modes
kind: concept
status: active
updated: 2026-04-14
source_count: 7
---

# Run Modes

Use this note when the question is:
- "Do I run `init`, `daily`, `monthly`, or `backfill run`?"
- "How wide is this refresh?"
- "Will this incrementally patch the warehouse or rebuild downstream outputs?"

## Fast choice
| Command | Use it when | Scope |
| --- | --- | --- |
| `uv run nbadb init` | You need a first build or a full historical rebuild | Historical seasons from `--season-start` through `--season-end` |
| `uv run nbadb daily` | You want the normal recurring refresh | Current season, recent games inside `NBADB_DAILY_LOOKBACK_DAYS`, plus active player/team refresh |
| `uv run nbadb monthly` | You need a broader recent-history sweep | Last 3 seasons |
| `uv run nbadb backfill run` | You are recovering from failures or filling gaps | Targeted seasons, endpoints, and parameter patterns |

> [!warning]
> `daily`, `monthly`, and `backfill run` differ in extraction scope, but they all finish by rebuilding downstream tables in `replace` mode.

## Shared operator behavior
- pipeline commands prefer the Textual TUI when stdout is interactive and `--verbose` is not set
- first `Ctrl+C` attempts a graceful stop
- second `Ctrl+C` forces exit
- underscore-prefixed pipeline tables are internal operational state, not part of the public analytical contract

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| public command framing | `README.md` | quick-start and command summaries |
| run-mode semantics and gotchas | `AGENTS.md` | maintainer contract |
| architecture lane | `docs/content/docs/start/architecture.mdx` | pipeline framing |
| CLI surface | `docs/content/docs/start/cli-reference.mdx` | exact command lane |
| recurring refresh lane | `docs/content/docs/ops/daily-updates.mdx` | operator guidance |
| config default references | `src/nbadb/core/config.py` | settings backing behavior |
| orchestrator behavior | `src/nbadb/orchestrate/orchestrator.py` | runtime execution context |
