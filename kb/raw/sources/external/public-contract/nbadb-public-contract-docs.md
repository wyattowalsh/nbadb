---
title: nbadb Docs Getting Started
kind: raw-source
status: captured
source_url: https://nbadb.w4w.dev/docs
captured_on: 2026-04-14
capture_type: web-fetch-markdown
why_it_matters: Main docs front door that defines the public analytical surface and routes readers to installation, architecture, CLI, schema, and guide pages.
---

# Source Record
- Page title: `Getting Started | nbadb`
- Page role: docs entry page for the hosted public documentation.
- Declares the project as a public analytical model with DuckDB staging, SQL-first transforms, and export formats for DuckDB, SQLite, Parquet, and CSV.
- Highlights four core run modes: `init`, `daily`, `monthly`, and `backfill run`.

# Why It Matters
This page is the public contract index for the docs site. It does not just link to other pages; it tells readers which page owns which question, which surfaces are public, and which generated references are contract artifacts rather than hand-written prose. It is the best single source for the project's public information architecture.

# Key Excerpts
> "Welcome to the Arena Data Lab for nbadb: the control tower for getting from first install to first query, first refresh, and first production handoff."

> "nbadb turns the NBA stats surface into a public analytical model with DuckDB staging, SQL-first transforms, and exports for DuckDB, SQLite, Parquet, and CSV."

> "Use schema pages for table discovery, then switch to field-level definitions."

> "Some docs pages are hand-authored. Others are generated from schema metadata and lineage information."

> "Regenerate those outputs when code changes; do not hand-edit them."

# Capture Notes
- Captured via markdown fetch and normalized to the page's route guidance and public-surface claims.
- Especially valuable as a contract page because it distinguishes curated pages from generated contract pages.
- The page also establishes the shortest-path reading order for new external users: install, architecture, CLI, playground, then schema/data dictionary.
