# nbadb — Agent Instructions

## Project Overview

nbadb is a comprehensive NBA database built around the current `nba_api` runtime surface
with 152 registered extractors, 416 staging entries, 254 transform outputs,
and 255 schema-backed public tables.
It follows an ELT pipeline: extract from NBA API → stage in DuckDB → transform into the
analytics/star schema → export to SQLite/DuckDB/Parquet/CSV.

## Tech Stack

- Python ≥3.12, uv (package manager), hatchling (build)
- Polars 1.42.1 (primary DataFrame engine)
- DuckDB 1.5.4 (staging engine, zero-copy Arrow interchange)
- Pandera[polars] 0.32.1 (3-tier schema validation: raw → staging → star)
- SQLModel 0.0.39
- ty 0.0.56 (type checker), ruff (lint/format)
- Docs: Fumadocs 16 + Next.js 16 + pnpm + Tailwind v4

## Module Map

```text
src/nbadb/
├── extract/          # 152 registered extractors wrapping nba_api endpoints
│   ├── stats/        # Statistical endpoint extractors
│   ├── static/       # Static data extractors (players, teams, arenas, awards)
│   └── live/         # Live game data extractors
├── schemas/          # Pandera schema definitions
│   ├── raw/          # Raw extraction schemas
│   ├── staging/      # Staging schemas + STAGING_MAP-backed staging keys
│   └── star/         # Output table schemas for final analytics model
├── transform/        # 254 transform outputs (246 historical + 8 live snapshot outputs)
│   ├── dimensions/   # 18 dimension builders (dim_*)
│   ├── facts/        # 133 fact builders + 5 bridge builders
│   ├── derived/      # 19 aggregate builders (agg_* outputs live here)
│   └── views/        # 14 analytics_* builders
├── load/             # SQLite/DuckDB/Parquet/CSV loaders
├── orchestrate/      # Pipeline orchestration + staging map
├── cli/              # Typer CLI + Textual TUI surface
├── core/             # Config, database, logging, coverage helpers
├── agent/            # Natural-language query agent
├── kaggle/           # Kaggle download/upload integration
└── docs_gen/         # Auto-generates schema/data-dictionary/ER/lineage artifacts
```

Additional repo-owned surfaces:

```text
chat/                # Canonical Chainlit app surface; `nbadb chat` uses it when launcher files are present
src/nbadb/chat/      # Shared chat launcher, notebook, runtime, tracing, SQL, catalog, and memory helpers
kb/                  # Companion Obsidian-native knowledge base for maintainers and agents
```

## Key Conventions

### Coverage Trust Floor

- Preserve and improve full historical `nba_api` coverage for every year available per endpoint.
- If an endpoint/year/season-type combination is unavailable upstream or blocked by a known contract gap, classify it explicitly in audits/support matrices instead of silently dropping it.

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

- 3494 tests collected across 181 test files
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
uv run nbadb backfill run                          # Targeted gap backfill
uv run nbadb full                                 # Fill gaps (deprecated — use backfill)
uv run nbadb status --output-format json          # Machine-readable pipeline status
uv run nbadb scan --fail-on error --report-path artifacts/health/local/scan-report.json  # Hard assurance gate
uv run nbadb export --data-dir data/nbadb       # Export sqlite/duckdb/csv/parquet by default
uv run nbadb extract-completeness --require-full  # CI coverage gate
uv run nbadb extract-completeness --require-full --endpoint-analysis-docs-root /path/to/nba_api  # Full upstream docs/tools + runtime live contract gate
uv run nbadb migrate                              # Create/migrate pipeline tables
uv run nbadb schema                               # Star schema info + lineage
uv run nbadb ask "Who scored the most in 1996?"   # Natural-language query
uv run nbadb chat                                 # AI chat UI when chat/chainlit_app.py and chat/pyproject.toml are present
uv run nbadb audit-models                          # nba_api endpoint coverage audit
uv run nbadb lint-sql                              # SQLFluff lint on transformer SQL
uv run nbadb metadata --data-dir data/nbadb --output dataset-metadata.json  # Generate Kaggle metadata JSON
uv run nbadb journal-summary                       # Pipeline telemetry for docs admin
uv run nbadb download                             # Pull latest Kaggle dataset
uv run nbadb upload --data-dir data/nbadb -m "Automated update" --verify-remote  # Validate, push, and read back Kaggle bundle

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
  - `docs/lib/generated/{raw,staging,star}-reference.json`
  - `docs/lib/generated/{raw,staging,star}-dictionary.json`
  - `docs/lib/generated/{schema,lineage,schema-coverage,agent-catalog}.json`
  - `docs/lib/site-metrics.generated.ts`
  - `docs/table-profile.generated.json` when `data/nba.duckdb` exists
- `nbadb docs-autogen` prints `updated:` / `unchanged:` lines for each generated artifact.
- The docs site lives in `docs/` and uses Fumadocs 16 + Next.js 16 via pnpm.

## Chat + KB Workflow

- Treat `chat/` as the canonical app surface; `apps/chat/` is retired and should not be reintroduced. The CLI and notebook launchers should fail closed if `chat/chainlit_app.py` or `chat/pyproject.toml` are absent.
- Keep reusable chat logic in `src/nbadb/chat/`; path-based launchers, notebooks, and workflows should resolve through `chat/` plus these shared helpers.
- Treat `kb/` as intentional repo content, not scratch output.
- The KB is companion material: additive-first, Obsidian-native, and subordinate to repo canon such as `README.md`, `AGENTS.md`, `docs/`, and `src/nbadb/`.
- Keep project-safe shared vault surfaces tracked under `kb/.obsidian/templates/` and `kb/.obsidian/snippets/`, but do not commit volatile editor-local workspace state if it appears later.

## Internal Pipeline Tables (10)

These DuckDB tables track pipeline state — do not modify directly:

- `_pipeline_watermarks` — Load high-water marks (`last_load` on output tables after transform+load)
- `_extraction_journal` — Extraction run history
- `_pipeline_metadata` — Per-table row counts, schema hashes, and last-updated timestamps
- `_pipeline_metrics` — Per-extraction-endpoint timing and row counts
- `_transform_checkpoints` — Resume support for interrupted transforms
- `_transform_metrics` — Transform execution metrics
- `_schema_versions` — Column hash snapshots for drift detection
- `_schema_version_history` — Schema change history
- `_lane_metrics` — Full-extraction lane timing and success/failure totals
- `_staging_chunk_journal` — Durable staging-batch chunk hashes for resume-safe extraction persistence

## Gotchas

- **Import shadowing**: `nbadb/` directory at repo root shadows `src/nbadb/` — always use `--import-mode=importlib` for pytest
- **Settings caching**: `get_settings()` uses `@lru_cache` — tests must call `cache_clear()` via autouse fixture
- **Chat surface split**: `chat/` holds the app package and assets, while `src/nbadb/chat/` holds shared runtime helpers used by the CLI, notebooks, and focused validation jobs
- **Pipeline UI**: `init`, `daily`, `monthly`, and `full` use the Textual TUI when stdout is a TTY and `--verbose` is not set; CI/non-interactive runs get plain output
- **Graceful stop**: first `Ctrl+C` during pipeline commands cancels cleanly and preserves journal/checkpoint state; second `Ctrl+C` forces exit
- **ReadOnlyGuard**: Strips SQL comments, normalizes Unicode (NFKC), always wraps queries in LIMIT, uses word-boundary keyword matching
- **Season params**: `season_type` param format varies by endpoint; `DraftBoard` uses `season_year` (int), `PlayoffPicture` uses `season_id` (str "2YYYY")
- **Coverage messaging**: public trust-floor language should promise full-history preservation only where `nba_api` exposes it, and should require explicit classification of upstream-unavailable or contract-blocked combinations
- **SCD2 dimensions**: `dim_player` and `dim_team_history` use SCD Type 2 (surrogate keys, valid_from/valid_to/is_current); all other dimensions use Type 1
- **Transform naming**: `fact_box_score_*` is team-level, `fact_player_game_*` is player-level — intentional
- **fact_rotation**: Depends on `[stg_rotation_away, stg_rotation_home]` (UNION of both)
- **Quality checks**: `--quality-check` on pipeline commands is informational; empty-table warnings do not fail the command
- **scan assurance gate**: use `nbadb scan --fail-on error` for hard assurance; `run-quality` is deprecated and no longer the gate
- **`full` deprecated**: use `backfill` for targeted gap-filling instead
- **CI**: All GitHub Actions are SHA-pinned, all workflows have permissions blocks, timeout-minutes, and concurrency groups
