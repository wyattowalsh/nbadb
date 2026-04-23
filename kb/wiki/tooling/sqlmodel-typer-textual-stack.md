---
title: SQLModel, Typer, and Textual in nbadb
tags:
  - kb
  - tooling
  - sqlmodel
  - typer
  - textual
aliases:
  - CLI and Control Plane Stack
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# SQLModel, Typer, and Textual in nbadb

This repo has two very different application surfaces:
- a scriptable CLI for automation, CI, and power users
- an interactive terminal UI for long-running human-operated pipeline runs

The stack is split accordingly:
- SQLModel for the lightweight relational/control-plane layer
- Typer for the command-line contract
- Textual for the interactive operator experience

## Repo-specific usage
- `src/nbadb/core/db.py` uses SQLModel for the SQLite/control-plane side while DuckDB remains the analytical engine
- `src/nbadb/cli/app.py` defines the root `typer.Typer` app and registers command modules
- `src/nbadb/cli/commands/_helpers.py` switches between plain logs and the Textual UI
- `src/nbadb/cli/tui.py` wraps the same orchestrator work in an operator-friendly terminal dashboard

## Maintainer rules
- keep CLI semantics in Typer, not in Textual
- keep commands thin
- preserve non-interactive parity
- use SQLModel where relational modeling helps, not as a default for warehouse tables
- preserve graceful shutdown and resume semantics

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| dependency floor | `pyproject.toml` | package dependency truth |
| public CLI and stack framing | `README.md` | public summary |
| SQLModel and DuckDB split | `src/nbadb/core/db.py` | control-plane vs warehouse behavior |
| Typer app contract | `src/nbadb/cli/app.py` | root CLI registration |
| TUI/CLI branching behavior | `src/nbadb/cli/commands/_helpers.py` | interactive vs plain logs |
| command structure example | `src/nbadb/cli/commands/init.py` | CLI implementation pattern |
| command structure example | `src/nbadb/cli/commands/daily.py` | CLI implementation pattern |
| Textual surface | `src/nbadb/cli/tui.py` | operator UI layer |
