---
title: Kaggle Publishing Lane
tags:
  - kb
  - topics
  - kaggle
  - distribution
  - notebooks
aliases:
  - Kaggle Download Lane
  - Kaggle Publish Handoff
kind: concept
status: active
updated: 2026-05-07
source_count: 10
---

# Kaggle Publishing Lane

Use this note when the question is:
- "Which command should I use for Kaggle download vs. publish?"
- "Where does `dataset-metadata.json` come from?"
- "How do the public Kaggle notebooks relate to the dataset lane?"

## The two lanes
| Lane | Primary commands | What happens |
| --- | --- | --- |
| Download lane | `uv run nbadb download --data-dir data/nbadb` | Pulls the configured Kaggle dataset into the target data directory, copies cached files into place, and seeds `nba.duckdb` from `nba.sqlite` if DuckDB is missing. |
| Publish lane | `uv run nbadb metadata --data-dir data/nbadb`, `uv run nbadb upload --data-dir data/nbadb` | Regenerates Kaggle metadata from the table catalog and export inventory, then uploads whatever is already on disk in the target data directory. |

`uv run nbadb export` is the usual upstream step before publish when the local directory needs fresh SQLite, DuckDB, CSV, or Parquet artifacts.

## CLI contract
- `uv run nbadb download --data-dir <dir>` pulls the latest published Kaggle bundle into a local working directory.
- `uv run nbadb upload --data-dir <dir> --message "..."` publishes that directory to the configured Kaggle dataset slug.
- `uv run nbadb metadata --data-dir <dir> --output <path>` generates a standalone `dataset-metadata.json`.
- `upload` does not rebuild the dataset. It publishes the current on-disk state.
- The default Kaggle dataset slug comes from `NBADB_KAGGLE_DATASET` / `NbaDbSettings.kaggle_dataset`, which defaults to `wyattowalsh/basketball`.

## Kaggle client integration
- `nbadb.kaggle.client.KaggleClient` is the repo's Kaggle boundary.
- The client uses `kagglehub.dataset_download(...)` and `kagglehub.dataset_upload(...)`; the runtime dependency is declared in `pyproject.toml`.
- Download behavior is file-oriented: every file and subdirectory from the Kaggle cache is copied into `data_dir`.
- Upload behavior is file-oriented too: the project lock currently contains `kagglehub` 1.0.0, and latest-source review of 1.0.1 still shows `dataset-metadata.json` is uploaded as part of the bundle while no separate public page-metadata update path is exposed by `kagglehub`.
- If only `nba.sqlite` is present after download, `_seed_duckdb_from_sqlite()` attaches the SQLite file in DuckDB and materializes each table into a new `nba.duckdb`.

## Metadata generation
- `uv run nbadb metadata` calls `nbadb.kaggle.metadata.generate_metadata(...)`.
- `uv run nbadb upload` calls `KaggleClient.ensure_metadata(...)` first, so the publish lane does not rely on a hand-maintained JSON file.
- Generated metadata uses the configured Kaggle slug as the dataset `id` and derives `subtitle`, `description`, and `resources` from the warehouse table catalog plus the detected export inventory.
- When `data_dir` exists, the metadata reflects the real bundle shape on disk and upload-time generation fails if CSV headers do not match generated schema field order.
- When `data_dir` is omitted or does not exist, generation falls back to catalog-level preview metadata consistently across description and resources. Use an existing `--data-dir` for publish validation.
- Important path nuance: the standalone `metadata` command defaults to `./dataset-metadata.json`, while `upload` ensures `data_dir/dataset-metadata.json`.

## Notebook and public example relationship
- The README is the canonical repo-level list of the ten public Kaggle notebooks.
- Those notebooks are downstream showcase examples for the published dataset and star-schema outputs, not part of the dataset upload mechanism.
- The generated Kaggle dataset description mentions companion notebooks, but it does not enumerate notebook URLs; use the README and [[wiki/topics/published-examples-source-summary|Published Examples Source Summary]] for the concrete public-example index.
- Treat the notebooks as consumer-facing proof that the dataset is useful, while the download/upload lane remains the operational path that moves artifacts.

## Related notes
- [[wiki/operations/kaggle-distribution|Kaggle Distribution]]
- [[wiki/topics/published-examples-source-summary|Published Examples Source Summary]]
- [[wiki/topics/project-overview|Project Overview]]

## Provenance
| Claim or section | Repo or canonical material | Notes |
|------------------|----------------------------|-------|
| download and upload command framing | `README.md` | public CLI summary and notebook list |
| operator workflow for Kaggle routes | `docs/content/docs/guides/kaggle-setup.mdx` | canonical user-facing guide |
| exact CLI signatures and notes | `docs/content/docs/cli-reference.mdx` | distribution command matrix |
| configured default dataset slug and data-dir defaults | `src/nbadb/core/config.py` | settings contract |
| download CLI implementation | `src/nbadb/cli/commands/download.py` | Typer entrypoint |
| upload CLI implementation | `src/nbadb/cli/commands/upload.py` | Typer entrypoint and preflight metadata step |
| metadata CLI implementation | `src/nbadb/cli/commands/metadata.py` | standalone metadata generation path |
| Kaggle client integration and SQLite-to-DuckDB seeding | `src/nbadb/kaggle/client.py` | main integration boundary |
| dataset metadata assembly, inventory detection, and companion-notebook wording | `src/nbadb/kaggle/metadata.py` | generated Kaggle JSON contract |
| public notebook index and warehouse-facing mapping | `kb/wiki/topics/published-examples-source-summary.md` | KB companion note for notebook relationships |
