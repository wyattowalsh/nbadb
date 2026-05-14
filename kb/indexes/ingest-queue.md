---
title: Ingest Queue
tags:
  - kb
  - index
  - queue
aliases:
  - KB Ingest Queue
kind: index
status: active
updated: 2026-05-07
source_count: 26
---

# Ingest Queue

Current companion-KB queue and capture ledger. The anchor lanes are already landed; keep future work narrow and prefer grouped `raw/extracts/internal/*.md` manifests for repo-local syntheses.

Related: [[external-sources]] · [[internal-source-catalog]] · [[source-map]] · [[coverage]] · [[../wiki/index|KB Home]]

## Priority queue
| Priority | Collection | Source batch | Planned raw capture path(s) | Capture form | Planned note(s) | Status |
|----------|------------|--------------|-----------------------------|--------------|-----------------|--------|
| P0 | Repo anchors | `README.md`, `AGENTS.md` | `raw/extracts/internal/repo-canon-inventory.md` | extract | `wiki/index.md`, route pages | seeded |
| P0 | Public contract | `docs/content/docs/architecture.mdx`, `docs/content/docs/schema/index.mdx`, `docs/content/docs/data-dictionary/index.mdx`, `docs/content/docs/lineage/index.mdx`, `docs/content/docs/endpoints/index.mdx`, `docs/content/docs/guides/` | `raw/extracts/internal/docs-surface-inventory.md` | extract | `wiki/model/*`, `wiki/operations/*`, `wiki/routes/*` | seeded |
| P0 | Upstream NBA source | `nba_api`, `stats.nba.com`, NBA live JSON | `raw/sources/external/upstream-nba/` | source capture | `wiki/topics/nba-api-source-summary.md` | captured |
| P0 | Extractor surface | `src/nbadb/extract/registry.py`, `src/nbadb/extract/**/*`, `src/nbadb/orchestrate/staging_map.py` | `raw/extracts/internal/extractor-and-staging-inventory.md` | extract | `wiki/model/endpoint-coverage.md` | seeded |
| P1 | Coverage + audit | `artifacts/endpoint-coverage/*`, `src/nbadb/core/endpoint_coverage.py`, `src/nbadb/core/model_audit.py`, `src/nbadb/cli/commands/endpoint_support_matrix.py` | `raw/extracts/internal/endpoint-coverage-and-audit-manifest.md` | extract + source-summary bridge | `wiki/topics/endpoint-coverage-source-summary.md`, `wiki/topics/model-audit.md`, `wiki/topics/full-extraction-control-plane.md` | captured |
| P1 | Chat / NL query surface | `chat/**/*`, `src/nbadb/agent/**/*`, `src/nbadb/chat/**/*` | `raw/extracts/internal/chat-surface-manifest.md` | extract | `wiki/topics/analytics-skill-source-summary.md`, `wiki/topics/chat-surface.md`, `wiki/topics/query-agent.md` | captured |
| P1 | Docs autogen | `src/nbadb/docs_gen/**/*`, `src/nbadb/cli/commands/docs_autogen.py`, `docs/lib/generated/*`, optional `docs/table-profile.generated.json` | `raw/extracts/internal/docs-generator-manifest.md` | extract | `wiki/topics/docs-autogen.md`, `wiki/topics/docs-profiling-surface.md` | captured |
| P1 | Distribution | Kaggle dataset page, GitHub repo, PyPI package page | `raw/sources/external/distribution/` | source capture | `wiki/operations/kaggle-distribution.md` | captured |
| P1 | Data stack docs | DuckDB, Polars, Pandera, SQLModel docs | `raw/sources/external/data-stack/` | source capture | `wiki/tooling/*.md` | captured |
| P1 | Tooling + vault docs | uv, Typer, Textual, Obsidian Help, Dataview docs | `raw/sources/external/tooling-vault/` | source capture | `wiki/tooling/obsidian-vault-conventions.md` | captured |
| P1 | Published examples | Kaggle notebook URLs from `README.md` | `raw/sources/external/published-examples/` | source capture, currently stub-heavy | `wiki/topics/published-examples-source-summary.md` | captured |
| P2 | Docs app stack | Fumadocs, Next.js, DuckDB-WASM | `raw/sources/external/docs-app-stack/` | source capture | `wiki/topics/docs-app-stack.md` | captured |
| P1 | Deep NBA API references | endpoint-level upstream docs | `raw/sources/external/nba-api-deep/` | source capture | `wiki/topics/extractor-surface.md`, `wiki/topics/season-time-semantics.md` | captured |
| P1 | Deep warehouse docs | DuckDB SQL and tuning, Polars joins/database IO, Pandera checks | `raw/sources/external/warehouse-deep/` | source capture | `wiki/tooling/duckdb-polars-pandera-stack.md`, future warehouse-deep notes | captured |
| P2 | Deep docs framework docs | Fumadocs layouts and source APIs, Next.js App Router docs | `raw/sources/external/docs-framework-deep/` | source capture, some stub fallback | `wiki/topics/docs-app-stack.md`, `wiki/topics/docs-component-registry.md`, `wiki/topics/playground-lane.md` | captured |
| P2 | Deep agent runtime docs | LangChain, LangGraph, GitHub Copilot docs, Chainlit docs | `raw/sources/external/agent-runtime-deep/` | source capture, some stub fallback | `wiki/topics/chat-surface.md`, `wiki/topics/query-safety.md` | captured |
| P1 | Deep Kaggle docs | Kaggle API, kagglehub, datasets/kernel metadata docs | `raw/sources/external/kaggle-deep/` | source capture | `wiki/topics/kaggle-publishing-lane.md` | captured |
| P2 | Deep docs runtime docs | source search, content collections, route handlers, OG image, client components | `raw/sources/external/docs-runtime-deep/` | source capture | `wiki/topics/docs-search-surface.md`, `wiki/topics/docs-admin-surface.md`, `wiki/topics/export-share-artifacts.md` | captured |
| P2 | Deep visualization docs | Observable Plot, Plotly, matplotlib, Recharts, Mermaid docs | `raw/sources/external/viz-deep/` | source capture, some stub fallback | `wiki/topics/visualization-surface.md`, `wiki/topics/court-helper-internals.md` | captured |
| P2 | Deep LangGraph/LangChain docs | graph API, persistence, HITL, tools, prompt templates | `raw/sources/external/langgraph-deep/` | source capture, some stub fallback | `wiki/topics/chat-surface.md`, `wiki/topics/query-safety.md`, `wiki/topics/chainlit-runtime.md` | captured |
| P2 | Deep Chainlit docs | lifecycle hooks, elements, backend message, profiles | `raw/sources/external/chainlit-deep/` | source capture, some stub fallback | `wiki/topics/chainlit-runtime.md`, `wiki/topics/profile-settings-surface.md` | captured |
| P2 | Deep Copilot docs | product overview, model use, environment customization, policy docs | `raw/sources/external/copilot-deep/` | source capture, some stub fallback | `wiki/topics/prompt-assembly-and-capabilities.md`, `wiki/topics/profile-settings-surface.md` | captured |
| P2 | Deep docs admin docs | Recharts, TanStack Table, shadcn table/tabs | `raw/sources/external/docs-admin-deep/` | source capture, some stub fallback | `wiki/topics/docs-admin-surface.md`, `wiki/topics/docs-chrome-surfaces.md` | captured |
| P2 | Deep DuckDB-WASM docs | overview, ingestion, query, bindings, README | `raw/sources/external/duckdb-wasm-deep/` | source capture | `wiki/topics/duckdb-wasm-runtime.md`, `wiki/topics/playground-lane.md` | captured |
| P2 | Advanced NBA API docs | player tracking, hustle, draft drills, rotation, defended shots | `raw/sources/external/nba-api-advanced/` | source capture | `wiki/topics/court-helper-internals.md`, `wiki/topics/lineup-trend-helpers.md`, future advanced endpoint notes | captured |
| P2 | Kaggle notebook metadata | notebook metadata-only stubs for public examples | `raw/sources/external/kaggle-notebook-metadata/` | metadata-stub capture | `wiki/topics/published-examples-source-summary.md`, `wiki/topics/kaggle-publishing-lane.md` | captured |

## Queue rules
- Promote queue rows into [[source-map]] as soon as a `raw` capture exists.
- Prefer one note cluster per ingest batch; split later only when the note becomes crowded.
- Use `raw/extracts/internal/` for grouped repo-local manifests; reserve `raw/sources/internal/` for an exact file mirror only when a literal internal copy is necessary.
- Use `raw/sources/external/` for exact upstream captures and `raw/extracts/` for distilled or grouped material.
- If a source required a failure-aware stub, keep it in the same collection and replace it in a later batch rather than dropping the record.

## Provenance
- `README.md`
- `AGENTS.md`
- `pyproject.toml`
- repo inventory and source-manifest subagent outputs from 2026-04-14
