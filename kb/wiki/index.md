---
title: nbadb Knowledge Base
tags:
  - kb
  - nbadb
  - moc
  - overview
aliases:
  - nbadb KB Home
  - nbadb Wiki Home
kind: overview
status: active
updated: 2026-04-22
source_count: 7
---

# nbadb Knowledge Base

This `wiki` page is the root navigation hub for the companion `vault` under `kb/`.

The KB is additive-first. Existing docs, code, and committed project instructions remain `canonical material`. The KB exists to make the repo easier to navigate in Obsidian, preserve `provenance`, and reduce rediscovery work for maintainers and agents.

## Scope
- Topic: nbadb architecture, operations, warehouse model, query surfaces, and supporting tooling
- KB root: `kb`
- Vault mode: companion KB
- Status: active
- Non-goals:
  - Replacing the public docs site under `docs/`
  - Moving or renaming current `canonical material`
  - Treating generated docs artifacts as the only source of truth
  - Vendoring large local database binaries into `raw/`

## Canonical material
| Path | Authority | Notes |
|------|-----------|-------|
| `README.md` | authoritative | Public package and dataset overview |
| `AGENTS.md` | authoritative | Repo operating contract and module map |
| `docs/AGENTS.md` | authoritative | Docs app contract and generated-doc ownership |
| `docs/content/docs/` | authoritative | Public authored and generated docs surface |
| `src/nbadb/` | authoritative | Core extract, schema, transform, load, and agent code |
| `chat/skills/nba-data-analytics/` | authoritative | Analytics skill, query cookbook, and schema guide |

## Start by role
- [[wiki/routes/start-here|Start Here]]
- [[wiki/routes/analyst-route|Analyst Route]]
- [[wiki/routes/operator-route|Operator Route]]
- [[wiki/routes/contributor-route|Contributor Route]]
- [[wiki/routes/stakeholder-route|Stakeholder Route]]

## Browse by system area
- Warehouse model: [[wiki/model/table-family-guide|Table Family Guide]], [[wiki/model/schema-wayfinding|Schema Wayfinding]], [[wiki/model/lineage-wayfinding|Lineage Wayfinding]], [[wiki/model/endpoint-coverage|Endpoint Coverage]]
- Operations: [[wiki/operations/run-modes|Run Modes]], [[wiki/operations/kaggle-distribution|Kaggle Distribution]], [[wiki/operations/troubleshooting|Troubleshooting]]
- Tooling: [[wiki/tooling/duckdb-polars-pandera-stack|DuckDB, Polars, and Pandera in nbadb]], [[wiki/tooling/sqlmodel-typer-textual-stack|SQLModel, Typer, and Textual in nbadb]], [[wiki/tooling/obsidian-vault-conventions|Obsidian Vault Conventions for nbadb KB]]
- Project orientation: [[wiki/topics/project-overview|Project Overview]]
- Execution roadmap: [[wiki/topics/strict-source-complete-roadmap|Strict Source-Complete Roadmap]], [[wiki/topics/full-extraction-control-plane|Full Extraction Control Plane]], [[wiki/topics/live-snapshot-contract|Live Snapshot Contract]]

## Browse by topic family
- Use [[indexes/topic-family-map|Topic Family Map]] when you already know the area and want the shortest next hop.
- Use [[indexes/source-map|Source Map]] when you want `provenance` and raw/canonical source tracing.
- Use [[indexes/external-sources|External Sources]] when the question is upstream contracts or public references.

## KB maintenance
- Governance: [[config/note-admission|Note Admission]], [[config/ingest|Ingest Contract]], [[config/provenance|Provenance Contract]]
- Operational indexes: [[indexes/coverage|Coverage]], [[indexes/stub-replacement-queue|Stub Replacement Queue]], [[activity/log|Activity Log]]

## Current bridge surfaces
| Source or bridge | Current raw path | Current wiki target | Status |
|------------------|------------------|---------------------|--------|
| Project canon | `raw/extracts/internal/repo-canon-inventory.md` | `wiki/index.md` and route pages | seeded |
| Docs site surfaces | `raw/extracts/internal/docs-surface-inventory.md` | `wiki/model/*`, `wiki/operations/*`, `wiki/topics/docs-autogen.md` | seeded |
| Extractor and staging surfaces | `raw/extracts/internal/extractor-and-staging-inventory.md` | `wiki/model/endpoint-coverage.md` | seeded |
| Coverage and audit bridge | `raw/extracts/internal/endpoint-coverage-and-audit-manifest.md` | `wiki/topics/endpoint-coverage-source-summary.md`, `wiki/topics/model-audit.md`, `wiki/topics/full-extraction-control-plane.md` | captured |
| Docs generator bridge | `raw/extracts/internal/docs-generator-manifest.md` | `wiki/topics/docs-autogen.md`, `wiki/topics/docs-profiling-surface.md` | captured |
| Full extraction control bridge | `raw/extracts/internal/full-extraction-control-manifest.md` | `wiki/topics/full-extraction-control-plane.md`, `wiki/topics/live-snapshot-contract.md` | captured |
| Source-summary bridges | `wiki/topics/docs-site-source-summary.md`, `wiki/topics/nba-api-source-summary.md`, `wiki/topics/endpoint-coverage-source-summary.md`, `wiki/topics/analytics-skill-source-summary.md`, `wiki/topics/published-examples-source-summary.md` | maintained evidence notes for recurring KB questions | active |

## Related indexes
- [[indexes/canonical-material|Canonical Material]]
- [[indexes/docs-surface-map|Docs Surface Map]]
- [[indexes/skill-surface-map|Skill Surface Map]]
- [[indexes/internal-source-catalog|Internal Source Catalog]]
- [[indexes/external-sources|External Sources]]
- [[indexes/ingest-queue|Ingest Queue]]
- [[indexes/source-map|Source Map]]
- [[indexes/coverage|Coverage]]
- [[indexes/topic-family-map|Topic Family Map]]
- [[indexes/stub-replacement-queue|Stub Replacement Queue]]
- [[activity/log|Activity Log]]

## Vault conventions
- Link style: prefer Obsidian wikilink syntax for vault-local notes and Markdown links for external URLs.
- Attachments: default local supporting assets to `raw/assets/`.
- Metadata: maintain `tags`, `aliases`, `kind`, `status`, `updated`, and `source_count` where useful.
- Shared surfaces: keep project-safe note templates in `.obsidian/templates/` and snippets in `.obsidian/snippets/`.
- Dataview metadata: keep frontmatter flat and query-friendly.

## Open questions
- [ ] Which stub-heavy external captures are worth replacing first based on actual use?
- [ ] Which future additions would genuinely reduce navigation cost rather than just expand coverage?

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| companion KB purpose and non-goals | `README.md` | public project and docs framing |
| repo module map and command vocabulary | `AGENTS.md` | maintainer-facing operating contract |
| docs ownership boundary | `docs/AGENTS.md` | authored vs generated docs rules |
| route orientation | `docs/content/docs/index.mdx` | public docs landing |
| architecture and warehouse framing | `docs/content/docs/start/architecture.mdx` | ELT model and public surface |
| role-based reader routes | `docs/content/docs/start/onboarding.mdx` | analyst/operator route logic |
| analytics skill linkage | `chat/skills/nba-data-analytics/SKILL.md` | chat-side query surface |
