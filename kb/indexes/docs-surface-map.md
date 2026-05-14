---
title: Docs Surface Map
tags:
  - kb
  - index
  - docs
aliases:
  - nbadb Docs Surface Map
kind: index
status: active
updated: 2026-05-07
source_count: 8
---

# Docs Surface Map

Related: [[canonical-material]] · [[skill-surface-map]] · [[../wiki/index|KB Home]]

This index maps the committed docs `canonical material`, the docs implementation surface, and the generator-owned docs outputs.

## Docs framework
| Concern | Paths | Notes |
|---------|-------|-------|
| Docs framework | `docs/AGENTS.md`, `docs/package.json` | Fumadocs + Next.js docs app with pnpm and Tailwind v4 |
| Docs runtime | `docs/app/`, `docs/components/`, `docs/lib/`, `docs/source.config.ts`, `docs/next.config.mjs`, `docs/proxy.ts` | App Router, MDX registry, DuckDB-WASM playground, Mermaid, admin routes |
| Docs content graph | `docs/content/docs/meta.json` and section `meta.json` files | Defines nav order and section grouping |

## Public docs navigation
| Group | Paths |
|------|-------|
| Getting Started | `docs/content/docs/index.mdx`, `docs/content/docs/installation.mdx`, `docs/content/docs/architecture.mdx`, `docs/content/docs/cli-reference.mdx` |
| Reference schema and dictionary | `docs/content/docs/schema/`, `docs/content/docs/data-dictionary/` |
| Reference diagrams and lineage | `docs/content/docs/diagrams/`, `docs/content/docs/lineage/` |
| Endpoint reference | `docs/content/docs/endpoints/` |
| Guides and playground | `docs/content/docs/playground.mdx`, `docs/content/docs/guides/` |

## Generator-owned docs surfaces
| Output surface | Generator source |
|----------------|------------------|
| Schema references | `src/nbadb/docs_gen/schema_docs.py`, `src/nbadb/docs_gen/autogen.py` |
| Data dictionary references | `src/nbadb/docs_gen/data_dictionary.py`, `src/nbadb/docs_gen/autogen.py` |
| ER diagram | `src/nbadb/docs_gen/er_diagram.py`, `src/nbadb/docs_gen/autogen.py` |
| Lineage docs | `src/nbadb/docs_gen/lineage.py`, `src/nbadb/docs_gen/autogen.py` |
| Generated machine data | `src/nbadb/docs_gen/` |

## Refresh path
- `uv run nbadb docs-autogen --docs-root docs/content/docs`
- Generator code lives in `src/nbadb/docs_gen/`

## Provenance
- `docs/AGENTS.md`
- `docs/package.json`
- `docs/content/docs/meta.json`
- docs section `meta.json` files under `docs/content/docs/{schema,data-dictionary,diagrams,endpoints,lineage,guides}/`
- `src/nbadb/docs_gen/autogen.py`
- `src/nbadb/docs_gen/schema_docs.py`
- `src/nbadb/docs_gen/data_dictionary.py`
- `src/nbadb/docs_gen/lineage.py`
- `src/nbadb/docs_gen/er_diagram.py`
