---
title: Lineage Wayfinding
tags:
  - kb
  - model
  - lineage
aliases:
  - Lineage Routing
kind: concept
status: active
updated: 2026-04-14
source_count: 6
---

# Lineage Wayfinding

Use this page when the real question is not "what does this table look like?" but "where did this come from?" or "what breaks if this changes?"

## Read the possession left to right
```text
endpoint -> raw_* -> stg_* -> dim_/fact_/bridge_ -> agg_/analytics_
```

## Which lineage page to use
| If the question is... | Best page |
| --- | --- |
| "Where did this table come from?" | `docs/content/docs/model/lineage/table-lineage.mdx` |
| "Which upstream field fed this metric or key?" | `docs/content/docs/model/lineage/column-lineage.mdx` |
| "I need the exhaustive dependency graph." | `docs/content/docs/model/lineage/lineage-auto.mdx` |
| "Which endpoint family starts this chain?" | `docs/content/docs/sources/index.mdx` |

## What lineage tells you best
- debugging bad values
- impact analysis
- coverage reasoning
- documentation routing

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| ELT chain framing | `README.md` | public architecture summary |
| `raw`/`stg`/star vocabulary | `AGENTS.md` | maintainer contract |
| lineage routing | `docs/content/docs/model/lineage/index.mdx` | curated lineage hub |
| table-level tracing | `docs/content/docs/model/lineage/table-lineage.mdx` | curated example path |
| column-level tracing | `docs/content/docs/model/lineage/column-lineage.mdx` | field-level route |
| exhaustive graph | `docs/content/docs/model/lineage/lineage-auto.mdx` | generated lineage graph |
