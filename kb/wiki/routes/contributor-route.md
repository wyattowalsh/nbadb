---
title: Contributor Route
tags:
  - kb
  - routes
  - contributors
  - maintainers
aliases:
  - Maintainer Route
  - Build and Docs Route
kind: overview
status: active
updated: 2026-04-22
source_count: 6
---

# Contributor Route

Use this route when the job is changing code, fixing tests, updating docs, regenerating artifacts, or choosing the right local verification loop.

## Start in 30 seconds
| If you need to change... | Start here first |
| --- | --- |
| Python code or tests | `AGENTS.md`, then a narrow `ruff` / `ty` / `pytest --import-mode=importlib` loop |
| Generated docs or schema-owned artifacts | [[../topics/docs-autogen|Docs Autogen]] |
| Hand-authored docs or docs app UX | `docs/AGENTS.md`, then `cd docs && pnpm lint` |

> [!tip]
> Start with the smallest lane that proves your change. Run broader checks only when your edit crosses more surfaces.

## Start here by task type
| If the task is... | Start with | First proof |
| --- | --- | --- |
| Python code in `src/nbadb/` | `AGENTS.md` and `src/nbadb/` | `ruff`, `ty`, and a narrow `pytest --import-mode=importlib` run |
| Generated docs, schema docs, or lineage docs | [[../topics/docs-autogen|Docs Autogen]] | `uv run nbadb docs-autogen --docs-root docs/content/docs` |
| Hand-authored docs or docs app UX | `docs/AGENTS.md` and `docs/content/docs/` | `cd docs && pnpm lint` |
| Analytics questions or warehouse-facing examples | [[analyst-route|Analyst Route]] | one query or example against the right table family |
| Refresh, recovery, or data-gap work | [[operator-route|Operator Route]] | one successful status check and the narrowest correct rerun |

## Default contributor loop
- Read the nearest local contract first: `AGENTS.md` for repo work, `docs/AGENTS.md` for docs-app work.
- Keep changes narrow and verify the exact lane you touched.
- Regenerate docs-owned artifacts after schema or model changes.
- Use `--import-mode=importlib` for pytest because the repo root shadows `src/nbadb/`.
- If the issue is actually stale data or pipeline state, switch to [[operator-route|Operator Route]] early.

## Watch for
- `docs/content/docs/model/schema/*`, `docs/content/docs/model/dictionary/*`, `docs/content/docs/model/diagrams/er-auto.mdx`, `docs/content/docs/model/lineage/lineage-auto.mdx`, and `docs/lib/generated/*` are generator-owned surfaces.
- `dim_player` and `dim_team_history` are SCD2 tables; docs and examples should say when `is_current = TRUE` matters.
- Local analytics or quality checks usually assume a seeded `nba.duckdb`; use `uv run nbadb download` when you need a published dataset locally.

## Open next
- [[start-here|Start Here]]
- [[../topics/project-overview|Project Overview]]
- [[../topics/docs-autogen|Docs Autogen]]
- [[../../config/note-admission|Note Admission]]
- [[analyst-route|Analyst Route]]
- [[operator-route|Operator Route]]
- [[../operations/troubleshooting|Troubleshooting]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| contributor route framing | `docs/content/docs/start/onboarding.mdx` | contributor lane and first commands |
| source setup and generated-docs boundary | `docs/content/docs/start/installation.mdx` | contributor install path and docs ownership boundary |
| repo commands, module map, and pytest import rule | `AGENTS.md` | maintainer-facing operating contract |
| docs app ownership and generated artifact rules | `docs/AGENTS.md` | authored vs generated docs contract |
| `docs-autogen` command semantics | `docs/content/docs/start/cli-reference.mdx` | generator command and CLI surface |
| KB growth and maintenance governance | `kb/config/note-admission.md` | admission and maintenance rule set |
