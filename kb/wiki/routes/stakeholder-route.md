---
title: Stakeholder Route
tags:
  - kb
  - routes
  - stakeholders
  - docs
aliases:
  - Public Docs Route
  - Executive Reader Route
kind: overview
status: active
updated: 2026-04-16
source_count: 7
---

# Stakeholder Route

Use this route when the goal is understanding and communication: what `nbadb` is, what the public dataset contains, where the examples live, and what the current project or pipeline status looks like.

## Start in 30 seconds
| If you need to... | Start here |
| --- | --- |
| Understand the project | [[../topics/project-overview|Project Overview]] |
| Understand the public model | [[../model/schema-wayfinding|Schema Wayfinding]] |
| Check current status | [[operator-route|Operator Route]] |
| Find shareable examples | [[../topics/published-examples-source-summary|Published Examples Source Summary]] |

> [!tip]
> Stay on the public contract: architecture, schema, diagrams, examples, and status. Leave extractor and transform internals for contributor or operator routes.

## Route table
| Need today | Start here | First useful output |
| --- | --- | --- |
| High-level project story | [[../topics/project-overview|Project Overview]] | One clear ELT summary from source to export |
| Public dataset shape | [[../model/schema-wayfinding|Schema Wayfinding]] | One table-family view of `dim_*`, `fact_*`, `agg_*`, and `analytics_*` |
| Visual model overview | [[../topics/docs-site-source-summary|Docs Site Source Summary]] plus the public docs diagrams pages | One diagram you can share in a briefing |
| Example-led proof | [[../topics/published-examples-source-summary|Published Examples Source Summary]] | One example notebook or demo path tied to warehouse surfaces |
| Source breadth and coverage | [[../model/endpoint-coverage|Endpoint Coverage]] | One answer to "how much of the NBA API surface is covered?" |
| Current state or freshness | [[operator-route|Operator Route]] plus `uv run nbadb status --output-format json` | One current pipeline snapshot for handoff or status review |

## If you have the CLI handy
```bash
uv run nbadb schema
uv run nbadb status --output-format json
```

## What to open next
- [[../topics/project-overview|Project Overview]]
- [[../model/schema-wayfinding|Schema Wayfinding]]
- [[../model/endpoint-coverage|Endpoint Coverage]]
- [[../topics/published-examples-source-summary|Published Examples Source Summary]]
- [[operator-route|Operator Route]]
- [[start-here|Start Here]]

## Related notes
- [[../topics/docs-site-source-summary|Docs Site Source Summary]]
- [[../topics/nba-api-source-summary|NBA API Source Summary]]
- [[../operations/kaggle-distribution|Kaggle Distribution]]
- [[../operations/run-modes|Run Modes]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| stakeholder route framing and first action | `docs/content/docs/start/onboarding.mdx` | stakeholder lane points to architecture and `nbadb schema` |
| public system story and ELT framing | `README.md` | project overview and release surfaces |
| module map, counts, and output families | `AGENTS.md` | repo-level operating contract |
| public docs ownership and docs-app boundary | `docs/AGENTS.md` | public docs surface vs generated docs rules |
| schema and status command vocabulary | `docs/content/docs/start/cli-reference.mdx` | inspection commands and public CLI framing |
| examples and demo surfaces | `README.md` | published Kaggle notebooks list |
| project-overview and examples companion notes | `kb/wiki/topics/project-overview.md`, `kb/wiki/topics/published-examples-source-summary.md` | KB-local routing support |
