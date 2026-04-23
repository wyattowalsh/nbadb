---
title: Stub Replacement Queue
tags:
  - kb
  - index
  - queue
  - stubs
  - external
aliases:
  - External Stub Replacement Queue
kind: index
status: active
updated: 2026-04-14
source_count: 18
---

# Stub Replacement Queue

Known stub or failure-aware captures across `kb/raw/sources/external/**` that should be revisited when upstream access, routes, or fetch methods improve.

Related: [[external-sources]] · [[ingest-queue]] · [[source-map]] · [[../wiki/index|KB Home]]

Priority labels mirror the collection priorities already recorded in [[ingest-queue]].

| Path | Source URL | Reason | Replacement Priority | Linked Wiki Topics |
|------|------------|--------|----------------------|--------------------|
| `raw/sources/external/distribution/nbadb-pypi-package.md` | `https://pypi.org/project/nbadb/` | PyPI returned a JavaScript client challenge, so the note is a package-page fallback stub built from `pyproject.toml` and README evidence instead of the live package body. | `P1` | [[../wiki/operations/kaggle-distribution|kaggle-distribution]] |
| `raw/sources/external/tooling-vault/obsidian-help-properties.md` | `https://help.obsidian.md/Properties` | Direct fetches only returned the Obsidian help shell and preload metadata, so the note preserves page identity and relevance without the readable Properties body. | `P1` | [[../wiki/tooling/obsidian-vault-conventions|obsidian-vault-conventions]] |
| `raw/sources/external/published-examples/defense-decoded.md` | `https://www.kaggle.com/code/wyattowalsh/nba-defense-decoded` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/draft-combine-analysis.md` | `https://www.kaggle.com/code/wyattowalsh/nba-draft-combine-analysis` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/game-prediction.md` | `https://www.kaggle.com/code/wyattowalsh/nba-game-prediction` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/mvp-predictor.md` | `https://www.kaggle.com/code/wyattowalsh/nba-mvp-predictor` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/nba-aging-curves.md` | `https://www.kaggle.com/code/wyattowalsh/nba-aging-curves` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/play-by-play-insights.md` | `https://www.kaggle.com/code/wyattowalsh/nba-play-by-play-insights` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/player-archetypes.md` | `https://www.kaggle.com/code/wyattowalsh/nba-player-archetypes` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/player-dashboard.md` | `https://www.kaggle.com/code/wyattowalsh/nba-player-dashboard` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/player-similarity.md` | `https://www.kaggle.com/code/wyattowalsh/nba-player-similarity` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/published-examples/shot-chart-analysis.md` | `https://www.kaggle.com/code/wyattowalsh/nba-shot-chart-analysis` | Kaggle notebook fetches returned a generic shell, anti-bot challenge, or `CRAWL_NOT_FOUND`, so the note is a metadata stub built from the repo README and public Kaggle profile metadata. | `P1` | [[../wiki/topics/published-examples-source-summary|published-examples-source-summary]] |
| `raw/sources/external/docs-framework-deep/fumadocs-ui-navigation-overview.md` | `https://fumadocs.dev/docs/ui/navigation/overview` | The requested deep link now returns a Fumadocs not-found page; the capture only preserves the failure plus the hinted replacement path `/docs/ui/layouts/links`. | `P2` | [[../wiki/topics/docs-app-stack|docs-app-stack]] · [[../wiki/topics/docs-component-registry|docs-component-registry]] · [[../wiki/topics/playground-lane|playground-lane]] |
| `raw/sources/external/docs-framework-deep/fumadocs-ui-page.md` | `https://fumadocs.dev/docs/ui/page` | The requested deep link now returns a Fumadocs alternatives page after a `404`; the capture preserves the failure plus the suggested replacement path `/docs/ui/layouts/page`. | `P2` | [[../wiki/topics/docs-app-stack|docs-app-stack]] · [[../wiki/topics/docs-component-registry|docs-component-registry]] · [[../wiki/topics/playground-lane|playground-lane]] |
| `raw/sources/external/agent-runtime-deep/chainlit-docs-overview.md` | `https://chainlit.io/docs/overview` | The exact Chainlit docs overview URL returned `404`, so the note only tracks the missing target and the likelihood that Chainlit reorganized its docs paths. | `P2` | [[../wiki/topics/chat-surface|chat-surface]] · [[../wiki/topics/query-safety|query-safety]] |
| `raw/sources/external/agent-runtime-deep/github-copilot-for-business.md` | `https://docs.github.com/en/copilot/github-copilot-for-business` | The exact GitHub Copilot for Business URL returned `404`, so the note only preserves the broken plan-specific path and the hint that the docs were reorganized. | `P2` | [[../wiki/topics/chat-surface|chat-surface]] · [[../wiki/topics/query-safety|query-safety]] |
| `raw/sources/external/viz-deep/recharts-guide.md` | `https://recharts.org/en-US/guide` | The requested Recharts guide route was not fetchable and returned `404` or no usable body, so the capture is a blocked stub pending a better route or site-specific crawl. | `P2` | [[../wiki/topics/visualization-surface|visualization-surface]] · [[../wiki/topics/court-helper-internals|court-helper-internals]] · [[../wiki/topics/export-share-artifacts|export-share-artifacts]] |
| `raw/sources/external/langgraph-deep/langchain-prompt-templates.md` | `https://python.langchain.com/docs/concepts/prompt_templates/` | The legacy LangChain prompt-template URL now collapses to the generic overview page, and the current docs index did not expose a clear replacement concept page. | `P2` | [[../wiki/topics/chat-surface|chat-surface]] · [[../wiki/topics/query-safety|query-safety]] · [[../wiki/topics/chainlit-runtime|chainlit-runtime]] |

## Notes

- `P1` rows are the highest-value replacements because they sit on public distribution, Obsidian metadata conventions, or README-linked published-example surfaces.
- The ten Kaggle notebook rows are intentionally separate so replacement work can land incrementally without losing notebook-specific URLs.
- Some `P2` rows already carry upstream replacement hints inside the raw note; keep those hints attached to the original target rather than overwriting the original record.
- Close a row only after the corresponding raw note is upgraded from stub/failure-aware capture to a substantially readable source capture.
- When a row closes, update `source-map`, `coverage`, and `activity/log.md` in the same batch.

## Provenance

- `kb/indexes/external-sources.md`
- `kb/indexes/ingest-queue.md`
- `kb/indexes/source-map.md`
- `kb/raw/sources/external/distribution/nbadb-pypi-package.md`
- `kb/raw/sources/external/tooling-vault/obsidian-help-properties.md`
- `kb/raw/sources/external/published-examples/*.md`
- `kb/raw/sources/external/docs-framework-deep/fumadocs-ui-page.md`
- `kb/raw/sources/external/docs-framework-deep/fumadocs-ui-navigation-overview.md`
- `kb/raw/sources/external/agent-runtime-deep/chainlit-docs-overview.md`
- `kb/raw/sources/external/agent-runtime-deep/github-copilot-for-business.md`
- `kb/raw/sources/external/viz-deep/recharts-guide.md`
- `kb/raw/sources/external/langgraph-deep/langchain-prompt-templates.md`
