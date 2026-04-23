---
title: Topic Family Map
tags:
  - kb
  - index
  - topics
  - moc
aliases:
  - Topic Families
  - Topic Note Family Map
kind: index
status: active
updated: 2026-04-22
source_count: 4
---

# Topic Family Map

Related: [[../wiki/index|KB Home]] · [[canonical-material]] · [[source-map]] · [[coverage]]

Use this page as the Obsidian-first map for the current `wiki/topics/` note set. The families below are browsing lanes, not strict ontology. Each note appears once in its most useful first-hop family.

## At a glance
| Family | Best for | Jump |
|--------|----------|------|
| Model | schema, lineage, grain, and semantic surface questions | [Model](#model) |
| Docs | docs app, admin, search, and generator questions | [Docs](#docs) |
| Chat runtime | agent assembly, tools, services, and runtime behavior | [Chat runtime](#chat-runtime) |
| Helper modules | metrics, charts, comparison, and lineup/trend helpers | [Helper modules](#helper-modules) |
| Exports | artifacts, publishing, and outward-facing outputs | [Exports](#exports) |
| Ops | repo-wide orientation and maintenance decisions | [Ops](#ops) |
| Source summaries | shortest bridge from evidence into synthesis | [Source summaries](#source-summaries) |

## Model
Use this family when the question is about warehouse shape, extractor coverage, or lineage mechanics.

- [[../wiki/topics/upstream-nba-api|Upstream NBA API]]
- [[../wiki/topics/extraction-boundary|Extraction Boundary]]
- [[../wiki/topics/extractor-surface|Extractor Surface]]
- [[../wiki/topics/lineage-internals|Lineage Internals]]
- [[../wiki/topics/semantic-catalog-service|Semantic Catalog Service]]
- [[../wiki/topics/sql-validator-service|SQL Validator Service]]
- [[../wiki/topics/memory-store-internals|Memory Store Internals]]
- [[../wiki/topics/access-mode-contract|Access Mode Contract]]

## Docs
Use this family when the work touches the docs app, docs UI/runtime, admin/search surfaces, or docs-only playground behavior.

### Platform and generation
- [[../wiki/topics/docs-app-stack|Docs App Stack]]
- [[../wiki/topics/docs-component-registry|Docs Component Registry]]
- [[../wiki/topics/docs-generator-internals|Docs Generator Internals]]
- [[../wiki/topics/docs-autogen|Docs Autogen]]
- [[../wiki/topics/duckdb-wasm-runtime|DuckDB-WASM Runtime]]
- [[../wiki/topics/playground-lane|Playground Lane]]

### Admin, search, and observability
- [[../wiki/topics/docs-admin-control-center|Docs Admin Control Center]]
- [[../wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[../wiki/topics/docs-content-audit|Docs Content Audit]]
- [[../wiki/topics/docs-pipeline-dashboard|Docs Pipeline Dashboard]]
- [[../wiki/topics/docs-profiling-surface|Docs Profiling Surface]]
- [[../wiki/topics/docs-search-surface|Docs Search Surface]]
- [[../wiki/topics/search-query-expansion|Search Query Expansion]]
- [[../wiki/topics/docs-chrome-surfaces|Docs Chrome Surfaces]]
- [[../wiki/topics/docs-telemetry-health|Docs Telemetry and Health]]

## Chat Runtime
Use this family when the work touches query behavior, agent assembly, runtime backends, or analytics-skill behavior.

### Runtime services and backends
- [[../wiki/topics/chat-surface|Chat Surface]]
- [[../wiki/topics/copilot-backend-runtime|Copilot Backend Runtime]]
- [[../wiki/topics/sandbox-backend-modes|Sandbox Backend Modes]]
- [[../wiki/topics/sandbox-runtime-contract|Sandbox Runtime Contract]]
- [[../wiki/topics/chat-launcher-runtime-surface|Chat Launcher Runtime Surface]]
- [[../wiki/topics/chat-notebook-bootstrap|Chat Notebook Bootstrap]]
- [[../wiki/topics/chat-tracing-surface|Chat Tracing Surface]]
- [[../wiki/topics/profile-settings-surface|Profile and Settings Surface]]
- [[../wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly and Capabilities]]
- [[../wiki/topics/mcp-server-surface|MCP Server Surface]]
- [[../wiki/topics/chat-skill-surface|Chat Skill Surface]]
- [[../wiki/topics/web-context-tools|Web Context Tools]]
- [[../wiki/topics/query-agent|Query Agent]]
- [[../wiki/topics/query-safety|Query Safety]]

### User-facing chat behavior
- [[../wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[../wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[../wiki/topics/query-patterns|Query Patterns]]
- [[../wiki/topics/query-cookbook-families|Query Cookbook Families]]

## Helper Modules
Use this family when the task is in the Python helper layer that powers metrics, charts, comparisons, and lineup/trend analysis.

- [[../wiki/topics/metric-calculator-surface|Metric Calculator Surface]]
- [[../wiki/topics/visualization-surface|Visualization Surface]]
- [[../wiki/topics/court-helper-internals|Court Helper Internals]]
- [[../wiki/topics/comparison-similarity-helpers|Comparison and Similarity Helpers]]
- [[../wiki/topics/lineup-trend-helpers|Lineup and Trend Helpers]]

## Exports
Use this family when the question is about output packaging, distribution artifacts, or handoff beyond the local warehouse.

- [[../wiki/topics/export-share-artifacts|Export and Share Artifacts]]
- [[../wiki/topics/kaggle-publishing-lane|Kaggle Publishing Lane]]
- [[../wiki/topics/artifact-store-internals|Artifact Store Internals]]

## Ops
Use this family when the task is operator-facing, maintenance-heavy, or mostly about repo-safe execution semantics.

- [[../wiki/topics/project-overview|Project Overview]]
- [[../wiki/topics/model-audit|Model Audit]]
- [[../wiki/topics/season-time-semantics|Season and Time Semantics]]
- [[../wiki/topics/full-extraction-control-plane|Full Extraction Control Plane]]
- [[../wiki/topics/live-snapshot-contract|Live Snapshot Contract]]

## Source Summaries
Use this family when you need the shortest bridge from raw or canonical material into a synthesized topic summary.

- [[../wiki/topics/docs-site-source-summary|Docs Site Source Summary]]
- [[../wiki/topics/nba-api-source-summary|NBA API Source Summary]]
- [[../wiki/topics/endpoint-coverage-source-summary|Endpoint Coverage Source Summary]]
- [[../wiki/topics/analytics-skill-source-summary|Analytics Skill Source Summary]]
- [[../wiki/topics/published-examples-source-summary|Published Examples Source Summary]]

## Wayfinding notes
- Current topic-note count: `60` notes under `kb/wiki/topics/`.
- Fastest repo-level re-entry point: [[../wiki/index|KB Home]].
- Best companion index for raw and canonical source tracing: [[source-map]].
- Best companion index for repo-authority boundaries: [[canonical-material]].
- Best companion rule for future growth: [[../config/note-admission|Note Admission]].

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| current topic inventory, note names, and topic-note count | `kb/wiki/topics/*.md` | direct maintained topic set used for grouping |
| vault-level navigation context and related index surface | `kb/wiki/index.md` | current KB home and linked note map |
| required provenance treatment for maintained KB notes | `kb/config/provenance.md` | companion-KB provenance contract |
| current coverage routing for maintained topic notes | `kb/indexes/coverage.md` | kept in sync with the maintained note set |
