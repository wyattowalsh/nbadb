---
title: Project Overview
tags:
  - kb
  - topics
  - overview
  - project
aliases:
  - nbadb Overview
kind: concept
status: active
updated: 2026-04-30
source_count: 7
---

# Project Overview

Use this note when you need the shortest repo-local answer to "what is nbadb, what does it produce, and where should I look next?"

## What nbadb is
`nbadb` is an analytics-first NBA warehouse built around the current `nba_api` runtime surface. The repo documents the system as ELT: extract upstream NBA data, stage it in DuckDB, transform it into the star and analytics model, then export the public outputs to DuckDB, SQLite, Parquet, and CSV.

## Choose your next note by intent
| If you need to... | Start here |
| --- | --- |
| Query or analyze data | [[../routes/analyst-route|Analyst Route]] |
| Run or recover the pipeline | [[../routes/operator-route|Operator Route]] |
| Change code or docs safely | [[../routes/contributor-route|Contributor Route]] |
| Understand the project at a high level | [[../routes/stakeholder-route|Stakeholder Route]] |

## Core surfaces
| Surface | What it means here | Go next |
| --- | --- | --- |
| `extract/` + `schemas/raw/` | Where upstream NBA data enters the repo | [[wiki/topics/extractor-surface|Extractor Surface]] |
| DuckDB staging + `schemas/staging/` | The normalized intermediate layer behind `stg_*` tables | [[wiki/model/schema-wayfinding|Schema Wayfinding]] |
| `transform/` + `schemas/star/` | The public warehouse model analysts query | [[wiki/model/table-family-guide|Table Family Guide]] |
| `docs/` | The public docs app and release-facing contract surface | [[wiki/topics/docs-app-stack|Docs App Stack]] |
| `src/nbadb/docs_gen/` | The generator lane behind schema, dictionary, ER, lineage, and site metrics | [[wiki/topics/docs-autogen|Docs Autogen]] |
| `chat/` | The richer chat and agent-facing analytical surface | [[wiki/topics/chat-surface|Chat Surface]] |

## Current project shape
- Runtime scope: `152` registered extractors, `414` staging entries, and `252` transform outputs (`244` historical/star outputs plus `8` live snapshot outputs).
- Primary stack: Python 3.13, Polars, DuckDB, Pandera, SQLModel, Typer, Textual.
- Public model families: `dim_*`, `fact_*`, `bridge_*`, `agg_*`, `analytics_*`.
- Release surfaces: hosted docs, PyPI package, and Kaggle dataset all point back to the same warehouse contract.

## Fast orientation
- Start with [[wiki/operations/run-modes|Run Modes]] if the question is operational.
- Start with [[wiki/model/table-family-guide|Table Family Guide]] if the question is "which table family?"
- Start with [[wiki/model/schema-wayfinding|Schema Wayfinding]] if the question is "which schema page or generated contract?"
- Start with [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]] if the question is about the public docs contract rather than internal code layout.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| project scope, ELT flow, output formats | `README.md` | public project framing |
| endpoint, extractor, staging, and output counts; module map; naming families | runtime audit/count verification; `AGENTS.md` | maintainer contract |
| docs app exists as a separate surface | `docs/AGENTS.md` | docs ownership and app boundary |
| repo-local canonical anchors | `raw/extracts/internal/repo-canon-inventory.md` | KB ingest seed |
| docs-surface boundary and planned KB coverage | `raw/extracts/internal/docs-surface-inventory.md` | KB ingest seed |
| public docs as release-facing contract layer | `raw/sources/external/distribution/nbadb-docs-site.md` | external capture |
| docs front door and public information architecture | `raw/sources/external/public-contract/nbadb-public-contract-docs.md` | external capture |
