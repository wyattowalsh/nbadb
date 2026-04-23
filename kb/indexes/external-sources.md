---
title: External Sources
tags:
  - kb
  - index
  - sources
  - external
aliases:
  - External Source Index
kind: index
status: active
updated: 2026-04-14
source_count: 116
---

# External Sources

Related: [[ingest-queue]] · [[internal-source-catalog]] · [[source-map]] · [[coverage]] · [[../wiki/index|KB Home]]

Companion index for public URLs already referenced by nbadb’s repo, package metadata, or published docs.

## Capture form legend
- `url-note`: URL, owner, and why it matters; no copied content yet
- `markdown-extract`: readable prose capture for docs pages
- `json-manifest`: metadata snapshot where structure matters
- `endpoint snapshot`: compact table of endpoints, params, result sets, or page sections

## External collections
| Collection | Priority | Source | Why capture it | Suggested raw capture form |
|------------|----------|--------|----------------|----------------------------|
| Upstream NBA data | P0 | `nba_api`, `stats.nba.com`, NBA live JSON | Upstream surface behind nbadb extractors and dataset `provenance` | `markdown-extract` + `endpoint snapshot` |
| Public contract | P0 | `nbadb.w4w.dev`, especially docs root, schema, data-dictionary, lineage, architecture | Published warehouse surface and generated reference pages | `markdown-extract` |
| Distribution | P0 | Kaggle dataset page | Public dataset title, subtitle, resource list, and distribution narrative | `json-manifest` + `markdown-extract` |
| Published examples | P1 | Kaggle notebook URLs listed in `README.md` | Public analytical use cases and narrative examples for the dataset | `url-note` |
| Release surface | P1 | PyPI package page | Public install/release surface separate from docs and Kaggle | `url-note` |
| Data stack docs | P1 | DuckDB, Polars, Pandera, SQLModel docs | Deep semantics for transforms, validation, and storage | `url-note`, then `markdown-extract` selectively |
| Tooling + runtime docs | P2 | uv, Typer, Textual, Ruff, ty, proxywhirl | Contributor and pipeline-ops context | `url-note` |
| Docs app stack | P2 | Fumadocs, Next.js, DuckDB-WASM | Needed for docs-site and playground-specific notes | `url-note` + selective `markdown-extract` |

## Captured anchors
| Collection | Raw path | Count | Status |
|------------|----------|-------|--------|
| Public contract | `raw/sources/external/public-contract/` | 6 | captured |
| Upstream NBA data | `raw/sources/external/upstream-nba/` | 5 | captured |
| Distribution | `raw/sources/external/distribution/` | 4 | captured, with PyPI stub |
| Data stack docs | `raw/sources/external/data-stack/` | 7 | captured |
| Tooling + vault docs | `raw/sources/external/tooling-vault/` | 6 | captured |
| Published examples | `raw/sources/external/published-examples/` | 10 | captured as Kaggle-aware stubs |
| Docs app stack | `raw/sources/external/docs-app-stack/` | 5 | captured |
| Deep NBA API references | `raw/sources/external/nba-api-deep/` | 6 | captured |
| Deep warehouse docs | `raw/sources/external/warehouse-deep/` | 7 | captured |
| Deep docs framework docs | `raw/sources/external/docs-framework-deep/` | 6 | captured, with Fumadocs stubs |
| Deep agent runtime docs | `raw/sources/external/agent-runtime-deep/` | 6 | captured, with Copilot and Chainlit stubs |
| Deep Kaggle docs | `raw/sources/external/kaggle-deep/` | 5 | captured |
| Deep docs runtime docs | `raw/sources/external/docs-runtime-deep/` | 5 | captured |
| Deep visualization docs | `raw/sources/external/viz-deep/` | 5 | captured, with Recharts stub |
| Deep LangGraph and LangChain docs | `raw/sources/external/langgraph-deep/` | 5 | captured, with prompt-template stub |
| Deep Chainlit docs | `raw/sources/external/chainlit-deep/` | 6 | captured, with lifecycle/profile stubs |
| Deep Copilot docs | `raw/sources/external/copilot-deep/` | 5 | captured, with Claude/policy stubs |
| Deep docs admin docs | `raw/sources/external/docs-admin-deep/` | 6 | captured, with Recharts and TanStack stubs |
| Deep DuckDB-WASM docs | `raw/sources/external/duckdb-wasm-deep/` | 5 | captured |
| Advanced NBA API docs | `raw/sources/external/nba-api-advanced/` | 5 | captured |
| Kaggle notebook metadata stubs | `raw/sources/external/kaggle-notebook-metadata/` | 10 | captured as metadata stubs |

## High-value captured files
- `raw/sources/external/public-contract/nbadb-public-contract-architecture.md`
- `raw/sources/external/public-contract/nbadb-public-contract-schema.md`
- `raw/sources/external/upstream-nba/nba-api-readthedocs-index.md`
- `raw/sources/external/upstream-nba/nba-api-live-boxscore.md`
- `raw/sources/external/distribution/nbadb-kaggle-dataset.md`
- `raw/sources/external/distribution/nbadb-pypi-package.md`
- `raw/sources/external/data-stack/duckdb-docs-index.md`
- `raw/sources/external/data-stack/pandera-polars.md`
- `raw/sources/external/tooling-vault/obsidian-help-home.md`
- `raw/sources/external/tooling-vault/dataview-docs-overview.md`
- `raw/sources/external/published-examples/nba-aging-curves.md`
- `raw/sources/external/published-examples/player-dashboard.md`
- `raw/sources/external/docs-app-stack/fumadocs-homepage.md`
- `raw/sources/external/docs-app-stack/nextjs-docs.md`
- `raw/sources/external/nba-api-deep/shotchartdetail.md`
- `raw/sources/external/nba-api-deep/boxscoretraditionalv3.md`
- `raw/sources/external/warehouse-deep/duckdb-llms-index.md`
- `raw/sources/external/warehouse-deep/polars-joins.md`
- `raw/sources/external/docs-framework-deep/nextjs-app-router.md`
- `raw/sources/external/docs-framework-deep/duckdb-wasm-repository.md`
- `raw/sources/external/agent-runtime-deep/langgraph-overview.md`
- `raw/sources/external/agent-runtime-deep/langchain-introduction.md`
- `raw/sources/external/kaggle-deep/kaggle-api-datasets-metadata-doc.md`
- `raw/sources/external/kaggle-deep/kaggle-api-kernels-metadata-doc.md`
- `raw/sources/external/docs-runtime-deep/nextjs-route-handlers.md`
- `raw/sources/external/docs-runtime-deep/nextjs-opengraph-image.md`
- `raw/sources/external/viz-deep/observable-plot.md`
- `raw/sources/external/viz-deep/plotly-python.md`
- `raw/sources/external/langgraph-deep/langgraph-persistence.md`
- `raw/sources/external/langgraph-deep/langgraph-human-in-the-loop.md`
- `raw/sources/external/chainlit-deep/chainlit-docs-home.md`
- `raw/sources/external/chainlit-deep/chainlit-plotly-element.md`
- `raw/sources/external/copilot-deep/what-is-github-copilot.md`
- `raw/sources/external/copilot-deep/customize-agent-environment.md`
- `raw/sources/external/docs-admin-deep/shadcn-table.md`
- `raw/sources/external/docs-admin-deep/shadcn-tabs.md`
- `raw/sources/external/duckdb-wasm-deep/duckdb-wasm-overview.md`
- `raw/sources/external/duckdb-wasm-deep/duckdb-wasm-data-ingestion.md`
- `raw/sources/external/nba-api-advanced/boxscoreplayertrackv3.md`
- `raw/sources/external/nba-api-advanced/gamerotation.md`
- `raw/sources/external/kaggle-notebook-metadata/nba-player-dashboard.md`
- `raw/sources/external/kaggle-notebook-metadata/nba-shot-chart-analysis.md`

## Notes
- Prefer ingesting one anchor per collection before drilling into leaves.
- When an external page is volatile or layout-heavy, capture the readable text first and add screenshots only if the visuals matter.
- Some public sites such as PyPI and parts of Obsidian Help required failure-aware stubs rather than clean markdown captures; those are still useful as durable target records.
- Kaggle notebook pages also required failure-aware stubs; the README notebook titles and descriptions remain the best stable public metadata currently available.
- Some deeper framework and agent-runtime pages also required stubs because the public URL moved or returned a 404 shell, but the durable target still matters for future refreshes.
- Deeper visualization and docs-runtime captures are now available for the docs, admin, and chat note cluster; Recharts and one LangChain prompt-template page still required stub treatment.
- Chainlit, Copilot, docs-admin, and notebook-metadata captures add more stub-heavy but still valuable target records for later refresh.

## Provenance
- `README.md`
- `pyproject.toml`
- `docs/AGENTS.md`
- subagent research summary from 2026-04-14
- `raw/sources/external/`
