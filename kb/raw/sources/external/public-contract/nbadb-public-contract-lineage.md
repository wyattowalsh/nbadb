---
title: nbadb Docs Data Lineage
kind: raw-source
status: captured
source_url: https://nbadb.w4w.dev/docs/lineage
captured_on: 2026-04-14
capture_type: web-fetch-markdown
why_it_matters: Public lineage contract page for tracing how nba_api sources become raw captures, staging tables, star outputs, and exported artifacts.
---

# Source Record
- Page title: `Data Lineage | nbadb`
- Page role: hand-authored lineage overview for the public docs site.
- Publicly advertises `4` lineage views and `100+` transform paths.
- Distinguishes curated lineage pages from generator-owned `lineage-auto.mdx` coverage.

# Why It Matters
This page defines the public chain-of-custody story for nbadb data. It is the contract page for answering where a table or field came from, what breaks if a schema changes, and when a reader should escalate from curated lineage examples to the exhaustive generated dependency graph. It also explains the naming and validation transition from API-native payloads to warehouse-safe columns.

# Key Excerpts
> "Follow ball movement from NBA API sources through staging and into the star schema."

> "Lineage is the film room for nbadb."

> "lineage-auto.mdx is generator-owned. Use the curated pages in this section for orientation, then use the generated map when you need exhaustive, code-sourced dependency detail."

> "Use lineage to find the stage where a field stopped being source-shaped and became warehouse-safe."

> "This introspects BaseTransformer.depends_on and staging schema metadata[\"source\"] to build lineage graphs automatically."

# Capture Notes
- Captured via markdown fetch; the page's basketball metaphors were retained only where they help explain technical intent.
- Contract value is highest around impact analysis, provenance tracing, and the curated-versus-generated lineage boundary.
- The page also provides an important public explanation of validation progression: raw preserves source shape, staging normalizes names and types, and star surfaces add analyst-facing constraints.
