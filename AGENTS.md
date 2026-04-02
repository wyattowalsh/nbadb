# nbadb — Agent Instructions

## Project Overview

nbadb is a comprehensive NBA database built around the current `nba_api` runtime surface
(147 endpoint classes), 151 registered extractors, and 118 star schema outputs.
It follows an ELT pipeline: extract from NBA API → stage in DuckDB → transform into the
analytics/star schema → export to SQLite/DuckDB/Parquet/CSV.

## Tech Stack

- Python 3.13, uv (package manager), hatchling (build)
- Polars 1.38 (primary DataFrame engine)
- DuckDB 1.4 (staging engine, zero-copy Arrow interchange)
- Pandera[polars] 0.29 (3-tier schema validation: raw → staging → star)
- SQLModel 0.0.37
- ty 0.0.19 (type checker), ruff (lint/format)
- Docs: Fumadocs 16 + Next.js 16 + pnpm + Tailwind v4

## Module Map

```text
src/nbadb/
├── extract/          # 151 registered extractors wrapping nba_api endpoints
│   ├── stats/        # Statistical endpoint extractors
│   ├── static/       # Static data extractors (players, teams, arenas, awards)
│   └── live/         # Live game data extractors
├── schemas/          # Pandera schema definitions
│   ├── raw/          # Raw extraction schemas
│   ├── staging/      # Staging schemas + STAGING_MAP-backed staging keys
│   └── star/         # Output table schemas for final analytics model
├── transform/        # 118 star schema outputs
│   ├── dimensions/   # 18 dimension builders (dim_*)
│   ├── facts/        # 64 fact builders + 5 bridge builders
│   ├── derived/      # 19 aggregate builders (agg_* outputs live here)
│   └── views/        # 12 analytics_* builders
├── load/             # SQLite/DuckDB/Parquet/CSV loaders
├── orchestrate/      # Pipeline orchestration + staging map
├── cli/              # Typer CLI + Textual TUI surface
├── core/             # Config, database, logging, coverage helpers
├── agent/            # Natural-language query agent
├── kaggle/           # Kaggle download/upload integration
└── docs_gen/         # Auto-generates schema/data-dictionary/ER/lineage artifacts
```

## Key Conventions

### Naming

- `dim_*` — Dimension tables (18)
- `fact_*` — Fact tables (64)
- `bridge_*` — Bridge tables (5)
- `agg_*` — Pre-aggregated rollups (19 current outputs; code lives under `transform/derived/`)
- `analytics_*` — Analytics convenience tables/views (12)
- `stg_*` — DuckDB staging tables generated from `STAGING_MAP`
- `raw_*` — Raw extraction data

### SqlTransformer Base Class

Most transformers (100+) extend `SqlTransformer(BaseTransformer)` — define `_SQL` as a ClassVar, no `transform()` override needed. The base class handles execution.

### Schema Validation

3-tier Pandera validation:

- **Raw**: Validates extracted DataFrames before staging
- **Staging**: Validates after DuckDB load
- **Star**: Validates final output tables
- `BaseSchema.Config.strict=False` — hard-fail on missing/type errors, soft-warn+strip extras

### Test Patterns

- 2113+ test functions collected across 144 test files
- `conftest.py` autouse fixture calls `get_settings.cache_clear()` (settings use `@lru_cache`)
- Use `--import-mode=importlib` — the `nbadb/` root dir shadows `src/nbadb/`

## Commands

```bash
# Setup
uv sync                          # Install dependencies
uv sync --extra dev              # Install with dev extras

# Quality
uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # Format
uv run ty check src/             # Type check
uv run pytest --import-mode=importlib tests/unit  # Unit tests
uv run pytest --import-mode=importlib tests/      # All tests

# Pipeline
uv run nbadb init --season-start 1946             # Full rebuild (resume-safe)
uv run nbadb daily                                # Incremental update
uv run nbadb monthly                              # Recent-season refresh
uv run nbadb backfill                              # Targeted gap backfill
uv run nbadb full                                 # Fill gaps (deprecated — use backfill)
uv run nbadb status --output-format json          # Machine-readable pipeline status
uv run nbadb run-quality --report-path artifacts/health/local/data-quality-report.json
uv run nbadb export --format sqlite --format parquet
uv run nbadb extract-completeness --require-full  # CI coverage gate
uv run nbadb migrate                              # Create/migrate pipeline tables
uv run nbadb scan                                 # Detect missing data and gaps
uv run nbadb schema                               # Star schema info + lineage
uv run nbadb ask "Who scored the most in 1996?"   # Natural-language query
uv run nbadb chat                                 # AI chat UI
uv run nbadb audit-models                          # nba_api endpoint coverage audit
uv run nbadb lint-sql                              # SQLFluff lint on transformer SQL
uv run nbadb metadata                              # Generate Kaggle metadata JSON
uv run nbadb journal-summary                       # Pipeline telemetry for docs admin
uv run nbadb download                             # Pull latest Kaggle dataset
uv run nbadb upload -m "Automated update"         # Push dataset to Kaggle

# Docs
uv run nbadb docs-autogen --docs-root docs/content/docs   # Regenerate docs artifacts
uv run python -m nbadb.docs_gen --docs-root docs/content/docs
cd docs && pnpm dev              # Dev server
cd docs && pnpm lint             # Docs lint
cd docs && pnpm format:check     # Docs formatting check
```

## Docs Workflow

- Hand-edit authored docs pages such as `cli-reference.mdx`, guides, and architecture pages.
- Do **not** hand-edit generated docs artifacts; regenerate them instead:
  - `docs/content/docs/schema/{raw,staging,star}-reference.mdx`
  - `docs/content/docs/data-dictionary/{raw,staging,star}.mdx`
  - `docs/content/docs/diagrams/er-auto.mdx`
  - `docs/content/docs/lineage/lineage-auto.mdx`
  - `docs/content/docs/lineage/lineage.json`
- `nbadb docs-autogen` prints `updated:` / `unchanged:` lines for each generated artifact.
- The docs site lives in `docs/` and uses Fumadocs 16 + Next.js 16 via pnpm.

## Internal Pipeline Tables (8)

These DuckDB tables track pipeline state — do not modify directly:

- `_pipeline_watermarks` — Incremental extraction high-water marks
- `_extraction_journal` — Extraction run history
- `_pipeline_metadata` — Pipeline configuration state
- `_pipeline_metrics` — Per-transformer timing and row counts
- `_transform_checkpoints` — Resume support for interrupted transforms
- `_transform_metrics` — Transform execution metrics
- `_schema_versions` — Column hash snapshots for drift detection
- `_schema_version_history` — Schema change history

## Gotchas

- **Import shadowing**: `nbadb/` directory at repo root shadows `src/nbadb/` — always use `--import-mode=importlib` for pytest
- **Settings caching**: `get_settings()` uses `@lru_cache` — tests must call `cache_clear()` via autouse fixture
- **Pipeline UI**: `init`, `daily`, `monthly`, and `full` use the Textual TUI when stdout is a TTY and `--verbose` is not set; CI/non-interactive runs get plain output
- **Graceful stop**: first `Ctrl+C` during pipeline commands cancels cleanly and preserves journal/checkpoint state; second `Ctrl+C` forces exit
- **ReadOnlyGuard**: Strips SQL comments, normalizes Unicode (NFKC), always wraps queries in LIMIT, uses word-boundary keyword matching
- **Season params**: `season_type` param format varies by endpoint; `DraftBoard` uses `season_year` (int), `PlayoffPicture` uses `season_id` (str "2YYYY")
- **SCD2 dimensions**: `dim_player` and `dim_team_history` use SCD Type 2 (surrogate keys, valid_from/valid_to/is_current); all other dimensions use Type 1
- **Transform naming**: `fact_box_score_*` is team-level, `fact_player_game_*` is player-level — intentional
- **fact_rotation**: Depends on `[stg_rotation_away, stg_rotation_home]` (UNION of both)
- **Quality checks**: `--quality-check` on pipeline commands is informational; empty-table warnings do not fail the command
- **run-quality exit semantics**: `nbadb run-quality` writes useful JSON/text output, but failed checks are currently reported without forcing a non-zero exit unless no checks ran or the command errors
- **`full` deprecated**: use `backfill` for targeted gap-filling instead
- **CI**: All GitHub Actions are SHA-pinned, all workflows have permissions blocks, timeout-minutes, and concurrency groups
