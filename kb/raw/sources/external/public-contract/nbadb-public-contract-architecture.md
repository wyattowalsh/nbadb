---
title: nbadb Docs Architecture
kind: raw-source
status: captured
source_url: https://nbadb.w4w.dev/docs/architecture
captured_on: 2026-04-14
capture_type: web-fetch-markdown
why_it_matters: Public architecture contract for the raw-to-staging-to-star pipeline, validation tiers, export formats, and the boundary between public outputs and internal pipeline state.
---

# Source Record
- Page title: `Architecture | nbadb`
- Page role: hand-authored architecture overview for the hosted docs site.
- Headline counts shown on page: `151` registered extractors, `118` public outputs, `4` export formats, and `8` internal state tables.
- Explicitly separates reader-facing public tables from underscore-prefixed operational tables.

# Why It Matters
This is one of the strongest public contract pages because it explains the system boundary in operational terms. It states what is public (`dim_*`, `fact_*`, `bridge_*`, `agg_*`, `analytics_*`), what is internal (`_pipeline_*`, `_transform_*`, `_schema_*` tables), how validation is layered, and how users should interpret daily versus historical run modes. It is the page most likely to be cited when someone asks what nbadb guarantees externally.

# Key Excerpts
> "Think of nbadb as an arena control tower for NBA data: extraction brings the game film in, DuckDB stages and validates it, transformers reshape it into analytics-ready tables, and export lanes package it for downstream use."

> "Transforms build the public analytical surface in dependency order."

> "daily, monthly, and backfill all finish by rebuilding downstream tables in replace mode. They are not row-level upsert commands against the public star surface."

> "Treat dimensions, facts, bridges, aggregates, and analytics outputs as the warehouse surface documented for analysts, downstream SQL, and exported datasets."

> "Treat underscore-prefixed tables such as _pipeline_watermarks, _extraction_journal, _pipeline_metadata, and _transform_checkpoints as operational state."

# Capture Notes
- Captured from the rendered markdown version of the page; Mermaid diagrams were summarized from the page's text fallback rather than copied in full.
- The page is unusually useful because it defines both the public contract and the non-contract operational machinery on one page.
- It also documents the docs ownership boundary by naming generator-owned outputs and the `docs-autogen` regeneration command.
