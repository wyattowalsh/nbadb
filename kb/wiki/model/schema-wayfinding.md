---
title: Schema Wayfinding
tags:
  - kb
  - model
  - schema
aliases:
  - Schema Routing
kind: concept
status: active
updated: 2026-04-14
source_count: 6
---

# Schema Wayfinding

Use this page when you know you are in the model layer but do not yet know which schema page, guide, or generated artifact should answer the question.

## Recommended reading order
| Step | Use this surface | Best for |
| --- | --- | --- |
| 1 | `docs/content/docs/model/schema/index.mdx` | Decide whether the question is about dimensions, facts, bridges, aggregates, or analytics views |
| 2 | Curated family guides under `docs/content/docs/model/schema/` | Pick the right table family and likely grain |
| 3 | `docs/content/docs/model/schema/relationships.mdx` | Confirm the cleanest join path |
| 4 | Generated schema pages | Verify exact contracts |
| 5 | Generated or curated data-dictionary pages | Decode column names, suffixes, and discriminators |

## Coverage caveat
The current schema coverage artifact reports a gap between lineage-tracked outputs and schema-backed outputs. If a table does not show up where you expect, do not assume it is absent from the codebase. Check lineage and transform code next.

## Practical defaults
- Start from curated schema docs if you still need judgment.
- Start from generated schema docs if you already know the exact table.
- Start from data dictionary docs if the confusion is column-level.
- Start from lineage docs if the confusion is provenance-level.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| public schema framing | `README.md` | docs pointers and warehouse framing |
| repo naming and validation tiers | `AGENTS.md` | authoritative maintainer contract |
| schema routing order | `docs/content/docs/model/schema/index.mdx` | curated schema hub |
| join-path guidance | `docs/content/docs/model/schema/relationships.mdx` | relationship lane |
| field-level interpretation | `docs/content/docs/model/dictionary/field-reference.mdx` | dictionary guidance |
| schema coverage caveat | `docs/lib/generated/schema-coverage.json` | generated coverage artifact |
