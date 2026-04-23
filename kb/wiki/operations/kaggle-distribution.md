---
title: Kaggle Distribution
tags:
  - kb
  - operations
  - kaggle
aliases:
  - Kaggle Delivery Lane
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Kaggle Distribution

Use this note when the question is:
- "How do I seed a local dataset from Kaggle?"
- "How does `nbadb upload` decide what to publish?"
- "What files should exist before or after a Kaggle handoff?"

## The two main paths
| Goal | Command | What happens |
| --- | --- | --- |
| Pull the published dataset into a local data directory | `uv run nbadb download` | Downloads the Kaggle dataset, copies files into the working data directory, and may seed DuckDB from SQLite |
| Publish the current local data directory to Kaggle | `uv run nbadb upload` | Ensures `dataset-metadata.json` exists, then uploads the directory to the configured Kaggle dataset slug |

## Metadata flow
```bash
uv run nbadb metadata --data-dir /path/to/data --output dataset-metadata.json
```

## Sharp edges
- `upload` publishes what is on disk; it does not rebuild the dataset for you.
- `download` is a seed path, not a validation path.
- authored docs and checked-in config disagree on the implied default `data_dir`; prefer explicit `NBADB_DATA_DIR` or `--data-dir`.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| Kaggle-facing package framing | `README.md` | public distribution pointers |
| project-level workflow and commands | `AGENTS.md` | maintainer summary |
| dataset URL and package metadata | `pyproject.toml` | project URLs |
| authored Kaggle guide | `docs/content/docs/ops/kaggle.mdx` | operator guidance |
| CLI route | `docs/content/docs/start/cli-reference.mdx` | user-facing command docs |
| config backing values | `src/nbadb/core/config.py` | default dataset slug and paths |
| download implementation | `src/nbadb/cli/commands/download.py` | local seed flow |
| upload implementation | `src/nbadb/cli/commands/upload.py` | publish flow |
