---
title: Internal Source Catalog
tags:
  - kb
  - index
  - sources
  - internal
aliases:
  - Internal Sources
kind: index
status: active
updated: 2026-04-22
source_count: 9
---

# Internal Source Catalog

Related: [[ingest-queue]] · [[external-sources]] · [[source-map]] · [[coverage]] · [[../wiki/index|KB Home]]

Repo-local source catalog for companion-KB work.

## Internal collections
| Collection | Priority | Paths / globs | Why this collection matters |
|------------|----------|---------------|-----------------------------|
| Project charter + operator docs | P0 | `README.md`, `AGENTS.md` | Establishes scope, commands, and repo workflow |
| Extractor inventory + source surface | P0 | `src/nbadb/extract/**/*`, `src/nbadb/extract/registry.py`, `src/nbadb/orchestrate/staging_map.py` | Defines extractor discovery and endpoint-to-staging grain mapping |
| Coverage + audit logic | P0 | `src/nbadb/core/endpoint_coverage.py`, `src/nbadb/core/model_audit.py`, `artifacts/endpoint-coverage/*` | Explains modeled vs excluded vs gap logic |
| Schema + transform contract | P0 | `src/nbadb/schemas/**/*`, `src/nbadb/transform/**/*`, `src/nbadb/core/transform_dependency_graph.py` | Core `raw` -> `stg` -> star contract plus transform dependency structure |
| Docs generators + generated contract | P1 | `src/nbadb/docs_gen/**/*`, `docs/content/docs/**/*`, `docs/lib/generated/*` | Shows how public docs artifacts are generated and where machine-readable contract data lives |
| Distribution + publication metadata | P1 | `dataset-metadata.json`, `src/nbadb/kaggle/**/*`, `notebooks/*_kernel-metadata.json` | Tracks how the dataset and notebooks are packaged for Kaggle |
| Chat + natural-language query surface | P1 | `src/nbadb/chat/**/*`, `src/nbadb/agent/**/*`, `chat/**/*` | Covers the shared chat runtime, app shell, query behavior, helper services, and skill content |
| CI + test guardrails | P1 | `.github/workflows/**/*`, `tests/**/*`, `tests/conftest.py` | Shows what the repo actually enforces in CI and tests |
| Built outputs + runtime artifacts | P2 | local DuckDB/SQLite/export outputs when present | Useful for validating shipped/public surface against docs and metadata without treating local build artifacts as stable repo canon |

## Catalog rules
- Prefer the smallest authoritative source: one file beats a derived summary.
- Capture generated JSON as `json snapshot`; capture human-authored docs as `full-source copy` or structured extract.
- Treat directory globs as collection manifests, not as a reason to ingest every file immediately.

## Provenance
- `README.md`
- `AGENTS.md`
- repo inventory subagent output from 2026-04-14
