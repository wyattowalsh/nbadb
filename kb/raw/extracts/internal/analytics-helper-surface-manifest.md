# Analytics Helper Surface Manifest

## Purpose
- Grouped internal extract for the `nba-data-analytics` helper surface shipped in `chat/skills/nba-data-analytics/scripts/`, plus the adjacent `query-cookbook` and `schema-guide` reference assets those helpers rely on.

## High-value paths

### Formula and season primitives
| Path | Inventory role | High-value callable surface |
| --- | --- | --- |
| `chat/skills/nba-data-analytics/scripts/metric_calculator.py` | Core metric formula library pre-imported as `mc` in `run_python` | `true_shooting_pct`, `effective_fg_pct`, `usage_rate`, `pace`, `offensive_rating`, `defensive_rating`, `net_rating`, `game_score`, `possessions`, `per_minute`, `assist_pct`, `steal_pct`, `block_pct`, `turnover_pct` |
| `chat/skills/nba-data-analytics/scripts/season_utils.py` | Season identifier/date helper module | `current_season`, `season_year_to_id`, `season_id_to_year` |

### Visualization and presentation helpers
| Path | Inventory role | High-value callable surface |
| --- | --- | --- |
| `chat/skills/nba-data-analytics/scripts/court.py` | Matplotlib half-court drawing and shot-location plotting | `draw_court`, `shot_chart`, `shot_heatmap`, `zone_chart`, `compare_shots` |
| `chat/skills/nba-data-analytics/scripts/team_colors.py` | Team-brand palette lookup for Plotly/matplotlib theming | `TEAM_COLORS`, `get_team_color`, `get_color_map` |
| `chat/skills/nba-data-analytics/scripts/compare.py` | Player-to-player comparison and normalization helpers | `compare_players`, `percentile_rank`, `radar_chart`, `per36`, `per100` |

### Statistical, similarity, and group analysis
| Path | Inventory role | High-value callable surface |
| --- | --- | --- |
| `chat/skills/nba-data-analytics/scripts/nba_stats.py` | Statistical testing and interval helpers that return JSON-serializable summaries | `is_significant`, `shooting_confidence`, `breakout_threshold`, `streak_significance` |
| `chat/skills/nba-data-analytics/scripts/similarity.py` | Player-comp and clustering utilities built around normalized numeric stat vectors | `normalize_stats`, `find_similar`, `cluster_players`, `career_similarity` |
| `chat/skills/nba-data-analytics/scripts/lineups.py` | On/off and lineup aggregation helpers | `on_off_impact`, `two_man_combos`, `lineup_chart` |
| `chat/skills/nba-data-analytics/scripts/trends.py` | Rolling-window, streak, breakout, and projection helpers over game-log style frames | `rolling_stats`, `detect_streaks`, `find_breakouts`, `season_projection` |

### Reference assets that route helper usage
| Path | Inventory role | High-value coverage |
| --- | --- | --- |
| `chat/skills/nba-data-analytics/references/query-cookbook.md` | SQL pattern library meant to be read from `run_python` when the ask moves beyond a single straightforward query | Year-over-year deltas, rolling windows, head-to-head, triple-double detection, efficiency-scatter inputs, shot-chart pulls, lineup efficiency, on/off impact |
| `chat/skills/nba-data-analytics/references/schema-guide.md` | Lightweight schema-routing note for choosing the right table family before or alongside helper use | Common `dim_*`, `fact_*`, `agg_*`, `analytics_*` surfaces; join templates; SCD2 reminders on `dim_player` and `dim_team_history` |

## Notes
- Runtime contract: `run_python` pre-imports `metric_calculator as mc`; the helper surface is intended as an execution-time convenience layer rather than a standalone package API.
- Data-shape bias: most helper modules assume pandas-style DataFrames with conventional nbadb column names such as `full_name`, `game_date`, `loc_x`, `loc_y`, `avg_net_rating`, and `on_off`.
- Visualization split is deliberate: `court.py` is matplotlib-based for shot geometry, while `lineups.py` and many user flows lean on Plotly-compatible outputs elsewhere in the chat runtime.
- Loose coupling exists inside the helper set: `compare.py` imports `_BG_COLOR` from `court.py` with a fallback, so court theming leaks into radar-chart presentation without a hard runtime dependency.
- Optional scientific stack: `nba_stats.py` uses SciPy when available for Shapiro, Welch/Mann-Whitney, Wilson intervals, and runs-test p-values; `similarity.cluster_players` also prefers SciPy k-means and falls back to quantile grouping.
- Surface overlap is intentional, not duplicate: `nba_stats.breakout_threshold` handles scalar/list summaries, while `trends.find_breakouts` handles DataFrame game-log workflows.
- Reference handoff pattern: `query-cookbook.md` is SQL-first but repeatedly hands control back to Python helpers (`court.*`, `lineups.on_off_impact`, Plotly scatter code) once the base dataset is pulled.
- Routing rule: `schema-guide.md` is a short wayfinding note, not the full schema catalog; the intended runtime behavior is still `list_tables` plus `describe_table` before guessing columns.

## Planned wiki coverage
- `kb/wiki/topics/analytics-skill-guide.md`
- `kb/wiki/topics/query-cookbook-families.md`
- `kb/wiki/topics/query-patterns.md`
- `kb/wiki/model/schema-wayfinding.md`
- `kb/wiki/topics/metric-calculator-surface.md`
- `kb/wiki/topics/visualization-surface.md`
- `kb/wiki/topics/court-helper-internals.md`
- `kb/wiki/topics/comparison-similarity-helpers.md`
- `kb/wiki/topics/lineup-trend-helpers.md`

## Provenance
- `chat/skills/nba-data-analytics/SKILL.md`
- `chat/skills/nba-data-analytics/scripts/metric_calculator.py`
- `chat/skills/nba-data-analytics/scripts/season_utils.py`
- `chat/skills/nba-data-analytics/scripts/court.py`
- `chat/skills/nba-data-analytics/scripts/team_colors.py`
- `chat/skills/nba-data-analytics/scripts/compare.py`
- `chat/skills/nba-data-analytics/scripts/nba_stats.py`
- `chat/skills/nba-data-analytics/scripts/similarity.py`
- `chat/skills/nba-data-analytics/scripts/lineups.py`
- `chat/skills/nba-data-analytics/scripts/trends.py`
- `chat/skills/nba-data-analytics/references/query-cookbook.md`
- `chat/skills/nba-data-analytics/references/schema-guide.md`
