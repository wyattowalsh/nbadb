---
title: nbadb Docs Schema Reference
kind: raw-source
status: captured
source_url: https://nbadb.w4w.dev/docs/schema
captured_on: 2026-04-14
capture_type: web-fetch-markdown
why_it_matters: Core public schema contract page defining the warehouse families, how to choose between curated versus generated references, and the current schema-backed coverage boundary.
---

# Source Record
- Page title: `Schema Reference | nbadb`
- Page role: curated schema entry page for the public warehouse model.
- Page reports `118 / 184 outputs` as currently schema-backed reference coverage (`64.1%`).
- Organizes the analytical surface into dimensions, facts, bridges, aggregates, analytics views, plus raw/staging/star reference tiers.

# Why It Matters
This page is the clearest public schema contract boundary. It tells readers what counts as the analytical surface, how to route by table family, when to rely on generated references for exact contracts, and that schema-backed coverage is intentionally narrower than total lineage coverage. That last point matters because it explicitly limits the current contract surface instead of implying every lineage-tracked output has a full schema guarantee.

# Key Excerpts
> "Schema-backed reference coverage is narrower than total lineage coverage."

> "An output counts as covered only when docs-autogen can pair a lineage-tracked output with a generated schema reference entry."

> "The nbadb analytical surface exposes public tables and views across dimensions, facts, bridges, derived aggregations, and analytics views."

> "Use curated pages for judgment and generated pages for verification."

> "Star first: dimensions create stable context around fact grains so common queries stay join-friendly."

# Capture Notes
- Captured from the public rendered page and reduced to the contract-relevant routing and coverage statements.
- Most important nuance: the page publicly admits that some modeled outputs remain outside the schema-backed contract layer.
- The generated `raw`, `staging`, and `star` references are treated as exact contract artifacts, while the family guides are treated as interpretive navigation.
