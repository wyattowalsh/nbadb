---
title: Sandbox Backend Modes
tags:
  - kb
  - topics
  - chat
  - sandbox
  - backend
  - daytona
  - e2b
aliases:
  - Sandbox Backend Selection
  - Remote Sandbox Modes
kind: concept
status: active
updated: 2026-04-15
source_count: 4
---

# Sandbox Backend Modes

Use this note for the narrow question: "how does `chat/server/_sandbox_backend.py` resolve `local` vs `daytona` vs `e2b`, sync remote assets, rewrite paths for remote runs, and keep `last_result` in sync?"

## Summary
`_sandbox_backend.py` is the mode selector and remote execution shim for Python chat analysis.

It does five jobs:
- resolves one validated sandbox mode from explicit input, environment, or chat settings
- dispatches `local` runs to the existing in-process sandbox executor
- stages DB, skill scripts, and session state into a remote workspace for `daytona` and `e2b`
- rewrites the preamble's embedded server path so remote imports still work
- pulls `last_result.parquet` back from the remote session after execution

## Mode Resolution
`resolve_sandbox_mode()` is local-first, but only after checking higher-precedence inputs.

Resolution order:
1. `explicit_mode` argument, if provided
2. `NBADB_CHAT_SANDBOX_MODE` from the passed `environ` or `os.environ`
3. `get_chat_settings().sandbox_mode.value`, but only if settings load successfully
4. fallback literal: `"local"`

Normalization and validation rules:
- strips whitespace and lowercases the candidate
- only accepts `local`, `daytona`, or `e2b`
- raises `ValueError` for anything else
- suppresses settings lookup failures and still falls back to `local`

Important precedence rule: an explicit mode overrides the environment variable.

## Backend Selection Rules
`run_python_in_sandbox()` is the single dispatch point.

Dispatch behavior:
- `local`: builds the preamble with the local DB, skills, and session paths, then calls `run_sandboxed(full_code, cwd=cwd, timeout=timeout)`
- `daytona`: skips `cwd`, stages remote assets, then runs `_run_in_daytona(...)`
- `e2b`: skips `cwd`, stages remote assets, then runs `_run_in_e2b(...)`

Two practical implications:
- only `local` uses the local subprocess sandbox directly
- both remote modes share the same remote workspace layout and preamble-building logic

## Remote Workspace Layout
Both remote backends standardize paths under `/workspace/nbadb`.

Canonical remote paths:
- database: `/workspace/nbadb/data/<db filename>`
- server helpers: `/workspace/nbadb/server`
- session state: `/workspace/nbadb/session`
- skill scripts: `/workspace/nbadb/skills`

The remote code is built against these paths, not the caller's local filesystem.

## Remote Asset Sync
`_prepare_remote_assets()` sends the minimum runtime payload needed for remote execution.

Always synced:
- the DuckDB database file to `_REMOTE_DATA_DIR / db_path.name`
- `chat/server/_safety.py` to `_REMOTE_SERVER_DIR / "_safety.py"`
- every `*.py` file directly under `skills_dir` to `_REMOTE_SKILLS_DIR / <filename>`

Conditionally synced:
- `session_dir / "last_result.parquet"`, but only if it already exists locally

Backend-specific transport:
- Daytona uses `sandbox.fs.upload_file(...)` after creating the remote folders
- E2B uses `sandbox.files.make_dir(...)` plus `sandbox.files.write(...)`

Notably absent:
- no recursive skill tree copy
- no sync of arbitrary files from `cwd`
- no general mirror of the local session directory beyond `last_result.parquet`

## Remote Path Rewriting
`_build_remote_code()` does not rebuild the preamble from scratch. It calls `build_preamble()` with remote DB, skills, and session paths, then patches one remaining local path reference.

What gets rewritten:
- the embedded local server directory string produced by `build_preamble()`

Why that rewrite exists:
- `build_preamble()` injects `__SERVER_DIR__` into `sys.path.insert(0, __SERVER_DIR__)`
- without rewriting, the remote sandbox would try to import helper modules such as `_safety` from the local machine path captured at build time

What does not need rewriting:
- DB path, skills path, and session path are already remote because `_build_remote_code()` passes remote values into `build_preamble()` up front

This is a targeted patch, not a generic path translation layer.

## `last_result` Sync
`last_result` persistence is split between the shared preamble and the backend shim.

Runtime flow:
1. the preamble loads `last_result` from `<session_dir>/last_result.parquet` if present
2. helper functions such as `table(df)` save the latest DataFrame back to that path
3. in remote modes, the preamble writes to `/workspace/nbadb/session/last_result.parquet`
4. after execution, `_sync_remote_last_result()` attempts to download that remote parquet file
5. if bytes are returned, the local `session_dir/last_result.parquet` is overwritten

Failure behavior:
- if the remote file is missing or unreadable, sync is skipped
- the helper does not delete the local file when the remote one is absent
- both remote backends call the sync step before interpreting stdout/stderr success

## Remote Backend Differences
The two remote backends share the same conceptual contract, but not the same SDK surface.

### Daytona
- imports `daytona.Daytona`
- creates a sandbox with `client.create()`
- runs code with `sandbox.process.code_run(...)`
- extracts stdout from `response.result`, stderr from `response.stderr`, and checks `response.exit_code`
- deletes the sandbox via `client.delete(sandbox)` in `finally`

### E2B
- tries `e2b_code_interpreter.Sandbox` first, then `e2b.Sandbox`
- creates the sandbox with `Sandbox.create()` when available, else `Sandbox()`
- runs code with `sandbox.run_code(...)`
- streams stdout/stderr through callbacks and falls back to execution logs when needed
- passes `build_clean_env()` into the remote run
- closes the sandbox via `kill()` or `close()` in `finally`

SDK import failures are returned as structured `{"error": ...}` responses, not re-raised.

## Maintainer Takeaways
- If mode selection behaves unexpectedly, inspect explicit arguments before env vars or settings.
- If remote imports break, inspect `_build_remote_code()` and the `__SERVER_DIR__` substitution first.
- If chat state does not carry across Python calls in remote mode, check whether `last_result.parquet` was uploaded before the run and downloaded after it.
- If a skill helper is missing remotely, remember only top-level `*.py` files in `skills_dir` are synced.

## Related Notes
- [[wiki/topics/sandbox-runtime-contract|Sandbox Runtime Contract]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/query-safety|Query Safety]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| supported modes, resolution order, dispatch rules, remote directory constants, asset sync, path rewriting, and last-result download | `chat/server/_sandbox_backend.py` | canonical implementation for backend choice and remote execution setup |
| preamble placeholders and injected server path, DB path, skills path, and session path | `chat/server/_preamble.py` | explains why `_build_remote_code()` only has to rewrite the embedded server directory |
| explicit-over-env precedence, local dispatch behavior, remote asset lists, remote path presence in generated code, and last-result round-trip expectations | `tests/unit/chat/test_sandbox_backend.py` | executable confirmation of intended behavior |
| higher-level runtime contract for how `last_result.parquet` is produced and consumed inside Python runs | `kb/wiki/topics/sandbox-runtime-contract.md` | companion note for the broader sandbox contract |
