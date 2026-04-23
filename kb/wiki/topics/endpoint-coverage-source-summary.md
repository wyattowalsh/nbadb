---
title: Endpoint Coverage Source Summary
tags:
  - kb
  - source
  - coverage
aliases: []
kind: source-summary
status: active
updated: 2026-04-22
source_count: 5
---

# Endpoint Coverage Source Summary

## Source record
| Field | Value |
|-------|-------|
| Source ID | `endpoint-coverage` |
| Raw source | `src/nbadb/core/endpoint_coverage.py`; `src/nbadb/core/model_audit.py`; `src/nbadb/cli/commands/endpoint_support_matrix.py`; `artifacts/endpoint-coverage/*`; `docs/content/docs/sources/index.mdx` |
| Capture or extract | `raw/extracts/internal/endpoint-coverage-and-audit-manifest.md` and `raw/extracts/internal/extractor-and-staging-inventory.md` |
| Status | captured |

## Summary
This source set defines two related but distinct audit surfaces: endpoint coverage for runtime/extractor/model ownership and model audit for stricter end-to-end inventory and baseline comparison.

## Planned wiki coverage
- `wiki/model/endpoint-coverage.md`
- `wiki/topics/model-audit.md`
- `wiki/topics/full-extraction-control-plane.md`

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|----------|-------|
| Coverage status taxonomy and explicit exclusions | `src/nbadb/core/endpoint_coverage.py` | Classification vocabulary |
| Summary payload structure | `src/nbadb/core/endpoint_coverage.py` | Coverage and star-schema coverage fields |
| Model audit modes | `src/nbadb/core/model_audit.py` | Audit modes and outputs |
| User-facing endpoint docs | `docs/content/docs/sources/index.mdx` | Current endpoint-family routing |
