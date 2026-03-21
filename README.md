# nbadb

[![PyPI](https://img.shields.io/pypi/v/nbadb)](https://pypi.org/project/nbadb/)
[![Python](https://img.shields.io/pypi/pyversions/nbadb)](https://pypi.org/project/nbadb/)
[![License](https://img.shields.io/github/license/wyattowalsh/nba-db)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/wyattowalsh/nba-db/ci.yml?label=CI)](https://github.com/wyattowalsh/nba-db/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/website?url=https%3A%2F%2Fnbadb.w4w.dev&label=docs)](https://nbadb.w4w.dev)
[![Kaggle](https://img.shields.io/badge/Kaggle-Dataset-blue?logo=kaggle)](https://www.kaggle.com/datasets/wyattowalsh/basketball)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.4-yellow?logo=duckdb)](https://duckdb.org)

The most comprehensive open NBA database available. **131 covered stats.nba.com endpoints** are extracted via [nba_api](https://github.com/swar/nba_api) and normalized into a **141-table star schema** spanning every NBA season from 1946 to present. Exports to DuckDB, SQLite, Parquet, and CSV, and is published as a [Kaggle dataset](https://www.kaggle.com/datasets/wyattowalsh/basketball) with 10 companion analysis notebooks.

> **131** Covered Endpoints · **141** Star Tables/Views · **395** Staging Entries · **143** Stats Extractors

## What's Inside

| Layer | Count | Description |
|-------|------:|-------------|
| **Dimensions** | 17 | Player, team, game, season, arena, coach, official, college, and more |
| **Facts** | 102 | Box scores, tracking, synergy, shot charts, lineups, draft, play-by-play |
| **Bridges** | 2 | Game-official and play-player many-to-many relationships |
| **Aggregates (`agg_`)** | 16 | Pre-aggregated rollups: per-game, per-36, per-48, career, rolling, leaders |
| **Analytics Views (`analytics_`)** | 4 | Wide, analysis-ready tables for common queries |
| **Total** | **141** | |

<details>
<summary><strong>Dimensions (17)</strong></summary>

`dim_all_players` · `dim_arena` · `dim_coach` · `dim_college` · `dim_date` · `dim_defunct_team` · `dim_game` · `dim_official` · `dim_play_event_type` · `dim_player` · `dim_season` · `dim_season_phase` · `dim_season_week` · `dim_shot_zone` · `dim_team` · `dim_team_extended` · `dim_team_history`

</details>

<details>
<summary><strong>Facts + Bridges (104)</strong></summary>

`bridge_game_official` · `bridge_play_player` · `fact_box_score_advanced_team` · `fact_box_score_defensive_team` · `fact_box_score_four_factors` · `fact_box_score_four_factors_team` · `fact_box_score_hustle_player` · `fact_box_score_misc_team` · `fact_box_score_player_track_team` · `fact_box_score_scoring_team` · `fact_box_score_starter_bench` · `fact_box_score_summary_v3` · `fact_box_score_team` · `fact_box_score_usage_team` · `fact_college_rollup` · `fact_cumulative_stats` · `fact_defense_hub` · `fact_draft` · `fact_draft_board` · `fact_draft_combine_detail` · `fact_fantasy` · `fact_franchise_detail` · `fact_game_context` · `fact_game_leaders` · `fact_game_result` · `fact_game_scoring` · `fact_homepage` · `fact_homepage_leaders` · `fact_ist_standings` · `fact_leaders_tiles` · `fact_league_dash_player_stats` · `fact_league_dash_team_stats` · `fact_league_game_finder` · `fact_league_hustle` · `fact_league_leaders_detail` · `fact_league_lineup_viz` · `fact_league_pt_shots` · `fact_league_shot_locations` · `fact_league_team_clutch` · `fact_lineup_stats` · `fact_matchup` · `fact_play_by_play` · `fact_player_available_seasons` · `fact_player_awards` · `fact_player_career` · `fact_player_dashboard_clutch_overall` · `fact_player_dashboard_game_splits_overall` · `fact_player_dashboard_general_splits_overall` · `fact_player_dashboard_last_n_overall` · `fact_player_dashboard_shooting_overall` · `fact_player_dashboard_team_perf_overall` · `fact_player_dashboard_yoy_overall` · `fact_player_estimated_metrics` · `fact_player_game_advanced` · `fact_player_game_hustle` · `fact_player_game_log` · `fact_player_game_misc` · `fact_player_game_tracking` · `fact_player_game_traditional` · `fact_player_headline_stats` · `fact_player_matchups` · `fact_player_next_games` · `fact_player_profile` · `fact_player_pt_reb_detail` · `fact_player_pt_shots_detail` · `fact_player_pt_tracking` · `fact_player_season_ranks` · `fact_player_splits` · `fact_playoff_picture` · `fact_playoff_series` · `fact_rotation` · `fact_scoreboard_detail` · `fact_scoreboard_v3` · `fact_season_matchups` · `fact_shot_chart` · `fact_shot_chart_league` · `fact_shot_chart_lineup` · `fact_standings` · `fact_streak_finder` · `fact_synergy` · `fact_team_awards_conf` · `fact_team_awards_div` · `fact_team_background` · `fact_team_dashboard_general_overall` · `fact_team_dashboard_shooting_overall` · `fact_team_estimated_metrics` · `fact_team_game` · `fact_team_game_hustle` · `fact_team_game_log` · `fact_team_historical` · `fact_team_history_detail` · `fact_team_hof` · `fact_team_lineups_overall` · `fact_team_matchups` · `fact_team_player_dashboard` · `fact_team_pt_reb_detail` · `fact_team_pt_shots_detail` · `fact_team_pt_tracking` · `fact_team_retired` · `fact_team_season_ranks` · `fact_team_social_sites` · `fact_team_splits` · `fact_tracking_defense` · `fact_win_probability`

</details>

<details>
<summary><strong>Aggregates (`agg_`) (16)</strong></summary>

`agg_all_time_leaders` · `agg_clutch_stats` · `agg_league_leaders` · `agg_lineup_efficiency` · `agg_on_off_splits` · `agg_player_bio` · `agg_player_career` · `agg_player_rolling` · `agg_player_season` · `agg_player_season_per36` · `agg_player_season_per48` · `agg_shot_location_season` · `agg_shot_zones` · `agg_team_franchise` · `agg_team_pace_and_efficiency` · `agg_team_season`

</details>

<details>
<summary><strong>Analytics Views (`analytics_`) (4)</strong></summary>

`analytics_head_to_head` · `analytics_player_game_complete` · `analytics_player_season_complete` · `analytics_team_season_summary`

</details>

For a browsable schema, generated raw/staging/star references, and column-level metadata, see the docs site: **[nbadb.w4w.dev](https://nbadb.w4w.dev/docs/schema)** and **[Data Dictionary](https://nbadb.w4w.dev/docs/data-dictionary)**.

## Data Coverage

All data spans from the **1946-47 season to present** (auto-updating via the daily pipeline).

- **Game-level** — box scores (traditional, advanced, misc, four factors, hustle, tracking), play-by-play, shot charts, rotations, win probability, game context, scoring runs
- **Player-level** — career stats, season splits, matchups, awards, draft combine measurements, player tracking (speed, distance, touches, passes, rebounding, shooting), estimated metrics
- **Team-level** — game logs, matchups, splits, clutch stats, franchise history, IST standings, playoff picture, pace and efficiency, player dashboards
- **League-level** — leaders, hustle stats, lineup visualizations, shot locations by zone, synergy play types, league-wide tracking

## Output Formats

| Format | Path | Description |
|--------|------|-------------|
| DuckDB | `nba.duckdb` | Primary analytics engine — columnar storage and fast SQL queries |
| SQLite | `nba.sqlite` | Portable single-file relational database |
| Parquet | `parquet/` | Zstd-compressed columnar files, partitioned by season |
| CSV | `csv/` | Universal flat files for any tool |

## Quick Start

```bash
pip install nbadb    # or: uv add nbadb

# Full build from scratch (1946-present, ~2-4 hours)
nbadb init

# Daily incremental update (~5-15 minutes)
nbadb daily

# Export to all formats
nbadb export

# Query with natural language
nbadb ask "who led the league in scoring last season"

# Upload to Kaggle
nbadb upload
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `nbadb init` | Full pipeline — extract all endpoints, stage, transform, export |
| `nbadb daily` | Incremental update for recent games |
| `nbadb monthly` | Dimension refresh + recent data |
| `nbadb full` | Full re-extraction without export |
| `nbadb migrate` | Run schema migrations |
| `nbadb run-quality` | Execute data quality checks and generate a report |
| `nbadb export` | Re-export DuckDB → SQLite / Parquet / CSV |
| `nbadb upload` | Push the dataset to Kaggle |
| `nbadb download` | Pull the Kaggle dataset and seed local DuckDB |
| `nbadb extract-completeness` | Report endpoint coverage gaps |
| `nbadb docs-autogen` | Regenerate generator-owned schema, data dictionary, ER, and lineage artifacts |
| `nbadb schema [TABLE]` | Show schema for a table or list all star tables |
| `nbadb status` | Pipeline status, row counts, and watermarks |
| `nbadb ask QUESTION` | Natural-language query interface (read-only) |

Run `nbadb --help` or `nbadb <command> --help` for full option details.

For docs-site maintenance, regenerate generator-owned artifacts with:

```bash
uv run nbadb docs-autogen --docs-root docs/content/docs
```

## AI Query Interface

`nbadb ask` translates natural-language questions into read-only DuckDB queries:

```bash
nbadb ask "top 5 players by career three-pointers made"
nbadb ask "which teams had the best home record in 2023-24"
nbadb ask "LeBron James career averages by season"
```

Queries run against the star schema with safety guards (read-only mode, query limits, SQL injection protection).

## Kaggle Notebooks

Ten analysis notebooks are published on Kaggle, all powered by this dataset:

| Notebook | Description |
|----------|-------------|
| [NBA Aging Curves](https://www.kaggle.com/code/wyattowalsh/nba-aging-curves) | Peak, prime, and decline — career trajectory modeling |
| [Defense Decoded](https://www.kaggle.com/code/wyattowalsh/nba-defense-decoded) | Tracking + hustle + synergy PCA to quantify defense |
| [Draft Combine Analysis](https://www.kaggle.com/code/wyattowalsh/nba-draft-combine-analysis) | What pre-draft measurements actually predict |
| [Game Prediction](https://www.kaggle.com/code/wyattowalsh/nba-game-prediction) | Stacking ensemble model for game outcomes |
| [MVP Predictor](https://www.kaggle.com/code/wyattowalsh/nba-mvp-predictor) | Explainable ML for MVP voting prediction |
| [Play-by-Play Insights](https://www.kaggle.com/code/wyattowalsh/nba-play-by-play-insights) | Win probability, scoring runs, and clutch analysis |
| [Player Archetypes](https://www.kaggle.com/code/wyattowalsh/nba-player-archetypes) | UMAP + GMM clustering — 8 data-driven player types |
| [Player Dashboard](https://www.kaggle.com/code/wyattowalsh/nba-player-dashboard) | Interactive explorer with 50+ metrics |
| [Player Similarity](https://www.kaggle.com/code/wyattowalsh/nba-player-similarity) | Find any player's statistical twin |
| [Shot Chart Analysis](https://www.kaggle.com/code/wyattowalsh/nba-shot-chart-analysis) | The geography of scoring and the 3-point revolution |

## Architecture

```text
stats.nba.com ──► Extract (143 stats extractors) ──► Stage (395 DuckDB staging entries)
                                                              │
                                                 Transform (141 star tables/views)
                         ┌────────────────┬────────────────┬────────────────┬───────────────────┬───────────────────┐
                         │ Dimensions     │ Facts          │ Bridges        │ Aggregates        │ Analytics Views   │
                         │ (17)           │ (102)          │ (2)            │ (16)              │ (4)               │
                         └────────────────┴────────────────┴────────────────┴───────────────────┴───────────────────┘
                                                              │
                                                   Export ────┼──────────┐
                                                   DuckDB  SQLite  Parquet/CSV
```

- **Polars** for all DataFrame operations with zero-copy Arrow interchange to DuckDB
- **3-tier Pandera validation** — raw → staging → star
- **SQL-first transforms** for the star surface, with dependency-ordered execution
- **SCD Type 2** for `dim_player` and `dim_team_history` (surrogate keys, `valid_from`/`valid_to`)
- **Checkpoint/resume** for interrupted transform runs
- **Watermark tracking** for incremental extraction
- **Proxy rotation** via proxywhirl with circuit-breaker failover

Read more in the full **[Architecture Guide](https://nbadb.w4w.dev/docs/architecture)**.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| DataFrames | [Polars](https://pola.rs/) 1.38 |
| Validation | [Pandera](https://pandera.readthedocs.io/) (Polars backend) |
| Analytics DB | [DuckDB](https://duckdb.org/) 1.4 |
| Relational DB | [SQLModel](https://sqlmodel.tiangolo.com/) + SQLite |
| HTTP / Proxy | [proxywhirl](https://github.com/wyattowalsh/proxywhirl) |
| CLI | [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) + [Textual](https://textual.textualize.io/) |
| Type Checking | [ty](https://github.com/astral-sh/ty) |
| Linting | [Ruff](https://docs.astral.sh/ruff/) |
| Docs | [Fumadocs](https://fumadocs.vercel.app/) + [Next.js](https://nextjs.org/) |
| CI | GitHub Actions (SHA-pinned) |

## Documentation

Full documentation lives at **[nbadb.w4w.dev](https://nbadb.w4w.dev)**.

- **[Getting Started](https://nbadb.w4w.dev/docs)** — install, run the pipeline, and learn where to go next
- **[Architecture](https://nbadb.w4w.dev/docs/architecture)** — pipeline stages, validation layers, and state tables
- **[Schema Reference](https://nbadb.w4w.dev/docs/schema)** — curated star-surface guide plus generated raw/staging/star references
- **[Data Dictionary](https://nbadb.w4w.dev/docs/data-dictionary)** — glossary plus generated raw/staging/star field references
- **[Diagrams](https://nbadb.w4w.dev/docs/diagrams)** — ER, endpoint map, and pipeline visuals
- **[Lineage](https://nbadb.w4w.dev/docs/lineage)** — trace endpoints and staging inputs to final tables
- **[Guides](https://nbadb.w4w.dev/docs/guides/role-based-onboarding-hub)** — onboarding, query recipes, Parquet, Kaggle, and troubleshooting

## License

MIT
