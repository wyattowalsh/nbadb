---
title: Docs Site Source Summary
tags:
  - kb
  - source
  - docs
aliases: []
kind: source-summary
status: active
updated: 2026-04-14
source_count: 5
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
This source set establishes that the docs site is a separate `docs/` app built on Fumadocs + Next.js, mixes hand-authored MDX with generator-owned reference artifacts, and relies on `nbadb docs-autogen` to refresh schema, data-dictionary, ER, lineage, and site-metrics outputs.

## Planned wiki coverage
- `wiki/model/schema-wayfinding.md`
- `wiki/model/lineage-wayfinding.md`
- future docs-autogen note

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Framework and docs app structure | `docs/AGENTS.md` | Establishes stack and directory layout |
| Package-level versions and scripts | `docs/package.json` | Confirms commands, dependencies, and Node requirement |
| Mermaid MDX configuration | `docs/source.config.ts` | Shows `remarkMdxMermaid` |
| Root nav ordering | `docs/content/docs/meta.json` | Confirms section layout |
| Docs generator outputs | `src/nbadb/docs_gen/autogen.py` | Shows generated docs and machine-readable outputs |
