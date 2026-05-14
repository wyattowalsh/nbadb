---
title: Docs Site Source Summary
tags:
  - kb
  - source
  - docs
aliases: []
kind: source-summary
status: active
updated: 2026-05-07
source_count: 6
---

# Docs Site Source Summary

## Source record
| Field | Value |
|-------|-------|
| Source ID | `docs-site` |
| Raw source | `raw/extracts/internal/docs-surface-inventory.md`; `raw/sources/external/public-contract/` |
| Capture or extract | internal docs-surface inventory plus public docs contract captures |
| Status | seeded |

## Summary
This source set establishes that the docs site is a separate `docs/` app built on Fumadocs + Next.js, now organized around root getting-started pages (`index`, `installation`, `architecture`, `cli-reference`), reference sections (`schema`, `data-dictionary`, `diagrams`, `endpoints`, `lineage`), and `guides/` plus `playground.mdx`. It still mixes hand-authored MDX with generator-owned reference artifacts and relies on `nbadb docs-autogen` to refresh schema, data-dictionary, ER, lineage, and site-metrics outputs.

## Planned wiki coverage
- `wiki/model/schema-wayfinding.md`
- `wiki/model/lineage-wayfinding.md`
- `wiki/topics/docs-autogen.md`
- `wiki/topics/docs-app-stack.md`
- `wiki/topics/docs-search-surface.md`

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Framework and docs app structure | `docs/AGENTS.md` | Establishes stack and directory layout |
| Package-level versions and scripts | `docs/package.json` | Confirms commands, dependencies, and Node requirement |
| Canonical hubs and navigation policy | `docs/AGENTS.md`; `docs/content/docs/meta.json`; section `meta.json` files | Current route contract |
| Root nav ordering | `docs/content/docs/meta.json` | Confirms top-level section layout |
| Hub-level content tree | `docs/content/docs/{schema,data-dictionary,diagrams,endpoints,lineage,guides}/`; root `installation.mdx`, `architecture.mdx`, `cli-reference.mdx`, `playground.mdx` | Current public docs topology |
| Docs generator outputs | `src/nbadb/docs_gen/autogen.py` | Shows generated docs and machine-readable outputs |
