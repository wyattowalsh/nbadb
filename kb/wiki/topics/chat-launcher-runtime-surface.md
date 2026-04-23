---
title: Chat Launcher Runtime Surface
tags:
  - kb
  - topics
  - chat
  - chainlit
  - cli
  - notebook
  - launcher
aliases:
  - Chat Launcher Surface
  - Chat CLI Launch Flow
kind: concept
status: active
updated: 2026-04-15
source_count: 9
---

# Chat Launcher Runtime Surface

This note covers `src/nbadb/chat/launcher.py` and the `nbadb chat` CLI route: how nbadb resolves `chat/chainlit_app.py`, chooses the Chainlit invocation path, hands off host and port, and shares the same launch helpers with the notebook bootstrap flow.

## App-path resolution
- `resolve_chat_app_dir()` treats the repo root as `Path(__file__).resolve().parents[3]` unless an explicit `project_root` is supplied.
- From that root, the chat app directory is always `chat`.
- `resolve_chainlit_app_path()` is a thin wrapper that appends `chainlit_app.py` inside that directory.
- Both the CLI route and command builder fail fast if `chainlit_app.py` is missing, so the launch surface assumes the richer Chainlit app lives in the checked-out repo tree rather than inside `src/nbadb`.

## Command and environment assembly
- `build_chainlit_env()` starts from the current process environment, then overlays `NBADB_CHAT_SANDBOX_MODE` when provided.
- `build_chainlit_command()` is the single place where host and port become Chainlit CLI flags.
- CLI-style launch uses `uv run chainlit run <app_file> --host <host> --port <port>`.
- Spawned launch uses `python -m chainlit run <app_file> --host <host> --port <port>` via `sys.executable`.
- The `uv` path is strict: if `use_uv=True` and `uv` is not on `PATH`, launcher code raises `RuntimeError`.

## Blocking CLI flow
- The public entrypoint is `[project.scripts].nbadb = "nbadb.cli.app:app"`.
- `src/nbadb/cli/app.py` imports `nbadb.cli.commands.chat`, and the `@app.command()` decorator registers `chat` on the main Typer app.
- `chat()` defaults to `host=127.0.0.1`, `port=8421`, and `sandbox_mode=local`.
- Before launching, the command resolves the app path and prints `Starting nbadb chat on http://{host}:{port} (sandbox={sandbox_mode})`.
- It then calls `run_chainlit_app(host=..., port=..., sandbox_mode=sandbox_mode.value)`.
- `run_chainlit_app()` is blocking and always runs with `cwd=chat`, so Chainlit starts relative to the app checkout rather than the caller's shell directory.
- CLI failures are normalized into user-facing Typer exits for missing app files, missing `uv`, or `subprocess.CalledProcessError`. `KeyboardInterrupt` prints a clean stop message instead of a traceback.

## Notebook launch relationship
- The notebook path is bootstrap-oriented, not a second CLI route.
- `resolve_notebook_chat_dir()` first looks upward for an existing `chat` checkout with both `chainlit_app.py` and `pyproject.toml`.
- If no local checkout is found, it clones a pinned repo ref into the notebook working directory and returns that checkout's `chat` directory.
- `install_chat_dependencies()` reads that checkout's `pyproject.toml` and installs declared dependencies into the current notebook interpreter with `pip`.
- After bootstrap, `notebooks/nba_chat_with_data.ipynb` calls `spawn_chainlit_app(...)` and then `wait_for_chainlit(process, BASE_URL)`.
- This flow deliberately uses `sys.executable -m chainlit` instead of `uv run chainlit`: the notebook has already prepared the active interpreter environment, so it does not rely on repo-local `uv` orchestration.

## Host and port handoff
- In both CLI and notebook paths, host and port are passed through unchanged into `build_chainlit_command()`.
- The launcher does not rewrite URLs, infer free ports, or add reverse-proxy behavior.
- The CLI route only echoes the final URL before delegating.
- The notebook flow additionally builds `BASE_URL = f"http://{HOST}:{PORT}"` and waits on that exact URL.
- `wait_for_chainlit()` polls with `httpx.get()` until it gets HTTP 200, the child process exits early, or the timeout expires.

## Surface split
- `run_chainlit_app()` is the foreground, CLI-facing surface.
- `spawn_chainlit_app()` is the background, notebook-facing surface.
- Both surfaces share the same app-path resolution, working directory, host and port serialization, and sandbox-mode environment handoff.
- `src/nbadb/chat/__init__.py` re-exports the launcher and notebook helpers, which makes them part of the broader `nbadb.chat` import surface even though the main operational callers are the CLI command and the example notebook.

## Related notes
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| app-path resolution and command/env builders | `src/nbadb/chat/launcher.py` | `resolve_chat_app_dir`, `resolve_chainlit_app_path`, `build_chainlit_env`, `build_chainlit_command` |
| blocking CLI handoff and user-visible defaults/errors | `src/nbadb/cli/commands/chat.py` | `chat()` command options, startup message, `run_chainlit_app(...)` call |
| Typer registration path for `nbadb chat` | `src/nbadb/cli/app.py` | command modules are imported to register decorators |
| console-script entrypoint | `pyproject.toml` | `[project.scripts] nbadb = "nbadb.cli.app:app"` |
| notebook checkout and dependency bootstrap | `src/nbadb/chat/notebook.py` | existing checkout preference, pinned clone fallback, pip install into current interpreter |
| notebook launch sequence | `notebooks/nba_chat_with_data.ipynb` | shared helpers, `spawn_chainlit_app(...)`, `wait_for_chainlit(...)`, `BASE_URL` |
| shared import surface | `src/nbadb/chat/__init__.py` | launcher and notebook helpers are re-exported |
| launcher behavior guards | `tests/unit/chat/test_launcher_and_notebook_helpers.py` | asserts app-path shape, local checkout preference, sandbox env propagation |
| CLI and notebook integration guards | `tests/unit/cli/test_chat_command.py`, `tests/unit/notebooks/test_nba_chat_with_data_launcher.py` | confirms host/port/sandbox handoff and notebook reliance on shared helpers |
