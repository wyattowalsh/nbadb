---
title: Canonical Material
tags:
  - kb
  - index
  - canonical-material
aliases:
  - nbadb Canonical Material
kind: index
status: active
updated: 2026-04-22
source_count: 7
---

# Canonical Material

Related: [[docs-surface-map]] · [[skill-surface-map]] · [[internal-source-catalog]] · [[../wiki/index|KB Home]]

Everything listed here is `canonical material` for the companion `vault`. Future `raw` imports should support or extend this material, not replace it.

## Authority rules
| Rule | Current interpretation |
|------|------------------------|
| Preserve committed docs and code | Treat tracked repo files as `canonical material` unless the repo itself marks them as generated or deprecated |
| Preserve generated ownership | Generated docs remain `canonical material`, but their source of truth is the generator pipeline rather than hand edits |
| Keep `provenance` explicit | Every maintained `wiki` claim should trace back to one or more canonical paths or explicit external captures |
| Do not promote caches to canon | Local caches, build artifacts, and runtime state are not `canonical material` unless explicitly ingested later |

## Canonical families
| Family | Paths | Why preserve |
|--------|-------|--------------|
| Project overview and operating model | `README.md`, `AGENTS.md`, `pyproject.toml` | Highest-signal summary of repo purpose, commands, dependency surface, and module map |
| Main application code | `src/nbadb/`, including `src/nbadb/chat/` | Primary source for extract, schema, transform, load, orchestrate, agent, chat runtime, and docs generator behavior |
| Docs app and docs content | `docs/AGENTS.md`, `docs/app/`, `docs/components/`, `docs/lib/`, `docs/content/docs/`, `docs/package.json` | Public docs and docs implementation surface |
| Chat companion shell | `chat/`, especially `chat/chainlit_app.py`, `chat/mcp_servers/`, and `chat/skills/` | App shell, compatibility entrypoints, and repo-local skill family layered over the shared runtime |
| Tests and fixtures | `tests/`, `tests/fixtures/` | Validation boundary and reproducible examples |
| Governance and publication metadata | `SECURITY.md`, `LICENSE`, `.github/CONTRIBUTING.md`, `.github/CODE_OF_CONDUCT.md`, `dataset-metadata.json` | Contributor, policy, and dataset-distribution boundary |

## Generated but still canonical
These paths are committed `canonical material`, but the repo already states that they are generator-owned and should be refreshed from code rather than rewritten manually.

| Path | Ownership note |
|------|----------------|
| `docs/content/docs/schema/raw-reference.mdx` | Generated docs artifact |
| `docs/content/docs/schema/staging-reference.mdx` | Generated docs artifact |
| `docs/content/docs/schema/star-reference.mdx` | Generated docs artifact |
| `docs/content/docs/data-dictionary/raw.mdx` | Generated docs artifact |
| `docs/content/docs/data-dictionary/staging.mdx` | Generated docs artifact |
| `docs/content/docs/data-dictionary/star.mdx` | Generated docs artifact |
| `docs/content/docs/diagrams/er-auto.mdx` | Generated docs artifact |
| `docs/content/docs/lineage/lineage-auto.mdx` | Generated docs artifact |
| `docs/lib/generated/` | Generated machine-readable docs backing data |

## Not canonical by default
- `.venv/`
- `.pytest_cache/`
- `.ruff_cache/`
- `dist/`
- `logs/`
- `.coverage`
- `data/nbadb/*.wal`
- `data/nbadb/*.shm`

## Provenance
- `README.md`
- `AGENTS.md`
- `pyproject.toml`
- `docs/AGENTS.md`
- `docs/content/docs/`
- `chat/skills/nba-data-analytics/SKILL.md`
- `SECURITY.md`
