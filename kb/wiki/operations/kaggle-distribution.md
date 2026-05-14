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
updated: 2026-05-07
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
| Pull the published dataset into a local data directory | `uv run nbadb download --data-dir data/nbadb` | Downloads the Kaggle dataset, copies files into the working data directory, and may seed DuckDB from SQLite |
| Publish the current local data directory to Kaggle | `uv run nbadb upload --data-dir data/nbadb --message "..."` | Ensures `dataset-metadata.json` exists, then uploads the directory to the configured Kaggle dataset slug |

## Metadata flow
```bash
uv run nbadb metadata --data-dir data/nbadb --output dataset-metadata.json
```

`nbadb upload` runs the same generator inside the target data directory before calling `kagglehub.dataset_upload(...)`. That generated sidecar is the copy source for Kaggle-facing dataset documentation and resource schemas.

## Sharp edges
- `upload` publishes what is on disk; it does not rebuild the dataset for you.
- `download` is a seed path, not a validation path.
- the configured default `data_dir` is `data/nbadb`; still prefer explicit `--data-dir data/nbadb` in publish commands to prevent operator ambiguity.
- upload-time metadata generation validates CSV headers against generated schema field order, because Kaggle resource schemas are order-bound.
- the project lock currently contains `kagglehub` 1.0.0, and latest-source review of 1.0.1 showed the same high-level upload limitation: files are uploaded and versions are created, but no separate public page-metadata update call is exposed in `kagglehub`.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| Kaggle-facing package framing | `README.md` | public distribution pointers |
| project-level workflow and commands | `AGENTS.md` | maintainer summary |
| dataset URL and package metadata | `pyproject.toml` | project URLs |
| authored Kaggle guide | `docs/content/docs/guides/kaggle-setup.mdx` | operator guidance |
| CLI route | `docs/content/docs/cli-reference.mdx` | user-facing command docs |
| config backing values | `src/nbadb/core/config.py` | default dataset slug and paths |
| download implementation | `src/nbadb/cli/commands/download.py` | local seed flow |
| upload implementation | `src/nbadb/cli/commands/upload.py` | publish flow |
