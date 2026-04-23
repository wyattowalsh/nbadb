---
title: Model Audit
tags:
  - kb
  - topics
  - audit
  - model
aliases:
  - Model Audit Engine
kind: concept
status: active
updated: 2026-04-22
source_count: 6
---

# Model Audit

`ModelAuditEngine` is the stricter audit surface that turns "we can extract it" into "we can account for it across runtime, staging, model, and schema contracts."

## What it checks
The inventory pass produces four audit layers:

| Layer | What it checks |
| --- | --- |
| `RuntimeSurface` | whether a runtime surface is represented by extractors, staging entries, and downstream model ownership |
| `StagingSurface` | whether each `stg_*` entry has extractor coverage, runtime coverage, downstream ownership, and input-schema coverage |
| `ModelSurface` | whether each runtime transform output has a registered star schema and resolved dependencies |
| `ColumnContract` | whether modeled output columns carry explicit origin metadata |

## Modes
| Mode | What it adds |
| --- | --- |
| `inventory` | static inventory only |
| `probe` | live probes against discovered params |
| `build` | live probes plus sampled `TransformPipeline` validation |
| `full` | same validation surface as `build`, written as the complete audit bundle |

## Why this exists even when endpoint coverage looks healthy
The current endpoint-coverage artifact shows the upstream/runtime/extractor surface is fully covered, but it also shows that modeling and contract coverage are still incomplete. That is the gap `model_audit.py` is designed to make explicit.

The grouped KB bridge for this lane now lives in [[wiki/topics/endpoint-coverage-source-summary|Endpoint Coverage Source Summary]] plus `raw/extracts/internal/endpoint-coverage-and-audit-manifest.md`.

## Related notes
- [[wiki/topics/endpoint-coverage-source-summary|Endpoint Coverage Source Summary]]
- [[wiki/topics/extractor-surface|Extractor Surface]]
- [[wiki/model/endpoint-coverage|Endpoint Coverage]]
- [[wiki/topics/full-extraction-control-plane|Full Extraction Control Plane]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| audit modes, strictness, decisions, and output bundle | `src/nbadb/core/model_audit.py` | canonical engine behavior |
| endpoint coverage summary and report | `artifacts/endpoint-coverage/endpoint-coverage-summary.json` | current generated snapshot |
| endpoint coverage narrative | `artifacts/endpoint-coverage/endpoint-coverage-report.md` | current generated snapshot |
| grouped coverage and audit bridge | `raw/extracts/internal/endpoint-coverage-and-audit-manifest.md` | KB bridge for support-matrix, coverage, and audit surfaces |
| positioning as stricter companion to endpoint coverage | `wiki/topics/endpoint-coverage-source-summary.md` | existing KB framing |
| extractor/staging context | `wiki/topics/extractor-surface.md` | supporting companion note |
