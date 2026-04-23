---
title: Chat Notebook Bootstrap
tags:
  - kb
  - topics
  - chat
  - notebooks
  - kaggle
aliases:
  - NBA Chat Notebook Bootstrap
  - Notebook Launcher Bootstrap
kind: concept
status: active
updated: 2026-04-15
source_count: 4
---

# Chat Notebook Bootstrap

This note covers the shared notebook bootstrap helpers in `src/nbadb/chat/notebook.py` and the tests that lock in the `notebooks/nba_chat_with_data.ipynb` launcher contract.

## What the helper module owns
`nbadb.chat.notebook` is the notebook-side bootstrap layer for the shared `chat` Chainlit app.

| Helper | Role | Important behavior |
| --- | --- | --- |
| `detect_notebook_work_dir()` | Pick a clone/work area | Returns `/kaggle/working` when `/kaggle` exists, otherwise `Path.cwd().resolve()` |
| `find_checked_out_chat_dir(start)` | Reuse an existing checkout | Walks upward from `start` or `cwd` and accepts only `chat` directories that contain both `chainlit_app.py` and `pyproject.toml` |
| `clone_pinned_repo(repo_url, repo_ref, work_dir)` | Materialize a pinned checkout | Clones into `<work_dir>/nbadb-<repo_ref[:8]>`, then runs `git checkout --detach <repo_ref>` |
| `resolve_notebook_chat_dir(...)` | Prefer reuse over download | Uses `find_checked_out_chat_dir(...)` first and only clones when no valid checkout is found |
| `ensure_local_duckdb(local_db, kaggle_db)` | Seed a writable local database | Leaves an existing local DB alone; otherwise copies bytes from the Kaggle-mounted DB if present |
| `install_chat_dependencies(chat_dir)` | Install the chat app runtime | Reads `project.dependencies` plus every optional dependency group from `pyproject.toml`, dedupes them, then runs `python -m pip install -q ...` |

## Bootstrap flow
The intended launcher flow is:
1. Add the repo `src/` directory to `sys.path` so notebook cells can import `nbadb` from a checkout.
2. Detect a notebook-friendly work directory, with a Kaggle-specific branch for `/kaggle/working`.
3. Resolve `chat` from an existing checkout if possible.
4. Otherwise clone a detached, pinned repo checkout for the requested ref.
5. Install the chat app's declared dependencies from `chat/pyproject.toml`.
6. Ensure a writable local `~/.nbadb/data/nba.duckdb` exists, seeding it from `/kaggle/input/basketball/nba.duckdb` when available.

## Notebook expectations
`notebooks/nba_chat_with_data.ipynb` is expected to use the shared helpers rather than reimplementing them inline.

The tests currently lock in these notebook expectations:
- Cell 1 imports `detect_notebook_work_dir`, `resolve_notebook_chat_dir`, and `install_chat_dependencies` from `nbadb.chat.notebook`.
- Cell 1 resolves `CHAT_DIR` through `resolve_notebook_chat_dir(...)` and installs dependencies through `install_chat_dependencies(CHAT_DIR)`.
- The notebook can recover the repo `src/` directory from a nested working directory under a checkout.
- Cell 2 persists `sandbox_mode` in the chat config, with the launcher default shown as `"local"`.
- Cell 3 imports and uses `ensure_local_duckdb`, with `KAGGLE_DB` set to `/kaggle/input/basketball/nba.duckdb` and `LOCAL_DB` set to `~/.nbadb/data/nba.duckdb`.
- Cell 5 launches via `spawn_chainlit_app(...)` and waits for readiness with `wait_for_chainlit(...)`.
- The notebook copy must surface an `Open NBA Chat` link after startup.

The notebook is also explicitly local-only: when running on Kaggle or Colab, it warns that localhost must be exposed by the platform rather than tunneling automatically.

## Test coverage shape
There are two relevant launcher test files:

| Test file | What it proves |
| --- | --- |
| `tests/unit/chat/test_launcher_and_notebook_helpers.py` | existing checkout discovery, `resolve_notebook_chat_dir(...)` preferring a local checkout, and local DuckDB seeding behavior |
| `tests/unit/notebooks/test_nba_chat_with_data_launcher.py` | the notebook imports the shared helpers, bootstraps `src/`, wires `sandbox_mode`, uses the shared DB helper, launches with the shared Chainlit helpers, and keeps the `Open NBA Chat` UX copy |

Coverage nuance:
- Checked-out chat dir discovery and local DuckDB seeding have direct unit tests.
- The notebook contract around helper usage has direct tests.
- Kaggle-aware work-dir detection, the actual pinned `git clone` plus detached checkout, and the real `pip install` subprocess path are implemented in `src/nbadb/chat/notebook.py` but are not directly unit-tested in the current launcher test files.

## Operational gotchas
- `clone_pinned_repo(...)` treats a pre-existing clone directory without a valid `chat` layout as an error, not something to overwrite.
- `install_chat_dependencies(...)` installs every optional dependency group, so the notebook bootstrap intentionally pulls the full chat runtime rather than a narrow minimal set.
- `ensure_local_duckdb(...)` does not create a DB when neither the local file nor the Kaggle-mounted input exists; the notebook falls back to the chat app's later download path.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/kaggle-publishing-lane|Kaggle Publishing Lane]]
- [[wiki/topics/published-examples-source-summary|Published Examples Source Summary]]

## Provenance
| Claim or section | Repo or canonical material | Notes |
|------------------|----------------------------|-------|
| helper responsibilities, work-dir detection, clone behavior, dependency install, DuckDB seeding | `src/nbadb/chat/notebook.py` | canonical implementation |
| direct helper tests for checkout discovery, local preference, and DB copy | `tests/unit/chat/test_launcher_and_notebook_helpers.py` | unit coverage for helper behavior |
| notebook launcher expectations and UX copy | `tests/unit/notebooks/test_nba_chat_with_data_launcher.py` | notebook contract tests |
| exact notebook cells, Kaggle DB path, sandbox default, localhost warning, and open-link output | `notebooks/nba_chat_with_data.ipynb` | source notebook consumed by the tests |
