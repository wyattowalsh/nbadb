---
title: Obsidian Vault Conventions for nbadb KB
tags:
  - kb
  - tooling
  - obsidian
  - dataview
aliases:
  - Vault Conventions
kind: concept
status: active
updated: 2026-04-22
source_count: 5
---

# Obsidian Vault Conventions for nbadb KB

## Current repo reality
`kb/` is an intentional companion vault in this repo. Shared vault config belongs under tracked project-safe surfaces such as `.obsidian/templates/`, `.obsidian/snippets/`, `config/`, `indexes/`, and maintained `wiki/` notes. Volatile editor-local state does not belong in the tracked KB surface.

## Core conventions
- prefer Obsidian wikilink syntax for note-to-note linking
- use YAML/frontmatter properties for note-level metadata
- use inline fields sparingly
- keep filenames in lowercase kebab-case
- separate KB content from generated docs
- use Dataview for discovery, not editing

## Linking convention
- use Obsidian wikilink syntax only for notes that exist inside the vault
- use code references for repo file paths such as `src/nbadb/core/db.py` and `docs/content/docs/lineage/lineage-auto.mdx`

## Vault policy for nbadb maintainers
If a fact is public-facing, stable, and part of the contract, put it in repo docs or code comments first.

If a fact is contextual, synthetic, operational, or research-heavy, the Obsidian KB is a good home.

When a maintained `wiki/` note is added or materially changed, update `indexes/coverage.md`, `indexes/source-map.md`, any touched `source_count` metadata, and `activity/log.md` in the same batch.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| intentional companion-vault status and tracked shared surfaces | `AGENTS.md` | repo-level KB contract |
| docs-site ownership boundary | `docs/AGENTS.md` | public docs stay canonical |
| shared vault config | `config/obsidian-vault.md` | project-safe vault rules |
| external Obsidian/Dataview targets | `indexes/external-sources.md` | external source map |
| captured Obsidian help and Dataview notes | `raw/sources/external/tooling-vault/` | current raw mirror collection |
