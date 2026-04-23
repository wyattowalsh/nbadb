---
title: Season Time Semantics
tags:
  - kb
  - topics
  - season
  - time
  - schema
aliases:
  - Season Identifier Semantics
  - Season Year vs Season ID
kind: concept
status: active
updated: 2026-04-14
source_count: 14
---

# Season Time Semantics

Use this note when a repo surface says `season`, `season_year`, `season_id`, or `season_type` and you need to know which shape is actually expected.

## Short version
- Canonical warehouse/reporting season key: `season_year` as `'YYYY-YY'`.
- Upstream `nba_api` season identifier: `season_id` as `'2YYYY'`.
- Some upstream endpoints want an integer start year instead of either string form.
- Canonical query discriminator is usually `season_year` plus `season_type`.
- The repo treats October as the season rollover month.

## Canonical forms
| Name | Shape | Example | Primary use in this repo |
| --- | --- | --- | --- |
| `season` | `'YYYY-YY'` string | `'2024-25'` | Orchestration, most extractor params, CLI parsing |
| `season_year` | `'YYYY-YY'` string | `'2024-25'` | Conformed star-schema season key and query filter |
| `season_id` | `'2YYYY'` string | `'22024'` | Some `nba_api` endpoints and a few source-shaped star tables |
| integer start year | `int` | `2024` | Endpoint-specific request kwargs such as `DraftBoard` |

## Repo default: `season_year` is the conformed season key
`src/nbadb/orchestrate/seasons.py` defines the main season helpers around the `'YYYY-YY'` string form:
- `season_string(2024) -> '2024-25'`
- `current_season()` returns the current `'YYYY-YY'` season
- `season_range()` and `recent_seasons()` both emit `'YYYY-YY'` strings

That same choice is reflected across the typed surface:
- `src/nbadb/core/types.py` defines `type SeasonYear = str`
- `CURRENT_SEASON` is computed from `current_season()`
- CLI backfill parsing converts a bare year like `2024` into `'2024-25'`

In the star schema, `season_year` is the normal reporting key. `dim_season` itself is built by grouping `stg_league_game_log` on `season_year`, then deriving season dates from `game_date`.

## `season_id` is upstream-shaped, not the main warehouse key
The chat skill scripts expose explicit converters:
- `season_year_to_id('2024-25') -> '22024'`
- `season_id_to_year('22024') -> '2024-25'`

That is a useful interoperability layer for `nba_api`, but not the repo's main warehouse convention.

Concrete evidence:
- `PlayoffPictureExtractor` converts a repo `season` string into `season_id = f"2{season[:4]}"` before calling the endpoint.
- AGENTS.md calls out this exact exception: `PlayoffPicture` uses `season_id` while `DraftBoard` uses integer `season_year`.

Important current-state gotcha:
- `chat/skills/nba-data-analytics/references/schema-guide.md` says `dim_season` has `season_id`.
- The current code does not: `src/nbadb/schemas/star/dim_season.py` defines `season_year`, `start_date`, `end_date`, `all_star_date`, and `playoff_start_date`.

Treat `season_id` as an endpoint/source compatibility shape, not the canonical analytical season dimension key.

## Some endpoints want integer `season_year`
Not every endpoint accepts the same season argument form.

Known repo-handled exceptions:
- `DraftBoardExtractor` converts `'2024-25'` to `season_year=2024`
- several draft combine extractors also pass `season_year=int(str(params['season'])[:4])`
- `DraftHistoryExtractor` uses `season_year_nullable=season`

This is why the repo keeps season helpers and per-endpoint adapters instead of assuming one universal request format.

## `season_type` is part of the grain
The repo treats `season_type` as a first-class discriminator, not an optional label.

Key behaviors:
- `SeasonType` enum values are `Regular Season`, `Playoffs`, `Pre Season`, and `All Star`.
- Pipeline orchestration defaults to `['Regular Season', 'Playoffs']` for init/backfill-style extraction.
- Discovery fetches `league_game_log` once per `(season, season_type)` pair when multiple types are requested.
- `BaseExtractor` injects a `season_type` column into result sets when the request included a season-type kwarg but the payload omitted the column.
- `fact_standings` normalizes missing values with `COALESCE(season_type, 'Regular Season')`.

Practical implication: if a question is season-scoped, the safe filter is usually both `season_year` and `season_type`.

## Current season rollover semantics
Both helper surfaces use the same rule: the NBA season turns over in October.

- `src/nbadb/orchestrate/seasons.py`: month `>= 10` means the new season has started
- `chat/skills/nba-data-analytics/scripts/season_utils.py`: same rule
- tests in `tests/unit/chat/test_skill_scripts.py` lock this in for September, October, November, and March cases

So:
- September 2025 -> `2024-25`
- October 2025 -> `2025-26`
- March 2026 -> `2025-26`

## Time-semantic gotchas
1. `season_year` is a string in the warehouse, even when an endpoint wants an integer start year.
2. `season_id` and `season_year` are not interchangeable without conversion.
3. `season_type` labels are not the same vocabulary as `SeasonPhase`.
   `SeasonType` uses values like `Pre Season` and `All Star`.
   `SeasonPhase` uses values like `Preseason`, `Regular`, `Play-In`, and `All-Star`.
4. Some star tables still preserve source-shaped `season_id` columns, for example `fact_team_game_log` and `dim_season_week`.
5. The safest analytical habit is the one already called out in the repo's analyst guidance: keep `season_year` and `season_type` explicit.

## Query guidance
- Prefer `season_year = '2024-25'` for warehouse queries.
- Add `season_type = 'Regular Season'` or `season_type = 'Playoffs'` unless the question truly spans both.
- Convert to `season_id` only when an upstream-compatible helper or endpoint requires it.
- Do not assume `dim_season` exposes `season_id` just because a secondary doc says so; check the current schema.

## Related notes
- [[wiki/topics/query-patterns|Query Patterns]]
- [[wiki/routes/analyst-route|Analyst Route]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/extractor-surface|Extractor Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| canonical `'YYYY-YY'` helpers and October rollover | `src/nbadb/orchestrate/seasons.py` | main orchestration season helpers |
| typed season aliases and enum values | `src/nbadb/core/types.py` | `SeasonYear`, `SeasonType`, `SeasonPhase`, `CURRENT_SEASON` |
| CLI season parsing rules | `src/nbadb/cli/commands/backfill.py` | accepts bare year, range, or full season string |
| extraction boundary injects `season_type` | `src/nbadb/extract/base.py` | reads several nba_api season-type kwarg names |
| default extraction season types | `src/nbadb/orchestrate/orchestrator.py` | defaults to Regular Season plus Playoffs |
| discovery by `(season, season_type)` pair | `src/nbadb/orchestrate/discovery.py` | game discovery semantics |
| AGENTS-level season param exceptions | `AGENTS.md` | `DraftBoard` integer `season_year`, `PlayoffPicture` string `season_id` |
| `PlayoffPicture` conversion to `season_id` | `src/nbadb/extract/stats/standings.py` | endpoint adapter |
| integer `season_year` endpoint handling | `src/nbadb/extract/stats/draft.py` | draft endpoints use integer start year or nullable season-year variants |
| chat-exposed season conversion helpers | `chat/skills/nba-data-analytics/scripts/season_utils.py` | `season_year_to_id()` and `season_id_to_year()` |
| chat prompt contract for `season_utils` | `chat/server/prompts.py` | helper advertised in run_python tool surface |
| chat sandbox imports skill scripts | `chat/server/_preamble.py` | `season_utils` is pre-imported |
| current `dim_season` contract | `src/nbadb/schemas/star/dim_season.py`, `src/nbadb/transform/dimensions/dim_season.py` | actual star-schema season dimension uses `season_year` |
| explicit analytical guardrail to keep season filters visible | `kb/wiki/routes/analyst-route.md`, `chat/skills/nba-data-analytics/references/schema-guide.md` | secondary guidance surface; useful but not more authoritative than code |
