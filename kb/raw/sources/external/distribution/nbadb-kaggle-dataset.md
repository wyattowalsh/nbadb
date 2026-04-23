---
title: "NBA Basketball Database Kaggle Dataset"
kind: raw-source
status: captured
source_url: "https://www.kaggle.com/datasets/wyattowalsh/basketball"
captured_on: "2026-04-14"
capture_type: dataset-page-plus-repo-sidecar
why_it_matters: "Most important public data distribution surface for nbadb: the downloadable dataset bundle that packages the warehouse for analysts who want DuckDB, SQLite, Parquet, or CSV outputs without running the full pipeline."
---

## Source Record

- Source: Kaggle dataset surface for `wyattowalsh/basketball`
- Scope captured: dataset title from the public Kaggle page plus the repository's published `dataset-metadata.json` sidecar that describes the same dataset bundle
- Capture date: `2026-04-14`

## Why It Matters

Kaggle is the clearest public distribution endpoint for the built data product itself. It tells downstream users what the released dataset is called, how it is packaged, and what coverage and formats nbadb publishes for direct consumption.

## Key Excerpts

> Kaggle page title at capture time: "NBA Database | Kaggle"

> Dataset sidecar title: "NBA Basketball Database"

> Dataset sidecar subtitle: "Comprehensive NBA database: 183-table star schema (1946-present) with DuckDB, SQLite, Parquet, and CSV exports"

> "Temporal coverage: 1946-47 through the current NBA season, with daily in-season refreshes and monthly full rebuilds."

## Capture Notes

- Direct Kaggle page fetch was partially blocked by anti-bot/challenge behavior; only the page title was recoverable from the surface itself.
- Repository-published `dataset-metadata.json` was used as the authoritative sidecar for the same Kaggle dataset identifier, `wyattowalsh/basketball`.
- This surface is high-value because it represents the distributable warehouse artifact, not just the source code that generates it.
