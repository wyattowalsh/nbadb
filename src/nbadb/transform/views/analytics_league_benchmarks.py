from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsLeagueBenchmarksTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_league_benchmarks"
    depends_on: ClassVar[list[str]] = [
        "agg_player_season",
        "agg_team_season",
    ]

    _SQL: ClassVar[str] = """
        WITH player_benchmarks AS (
            SELECT
                season_year,
                season_type,
                COUNT(DISTINCT player_id) AS total_players,
                AVG(avg_pts) AS league_avg_ppg,
                AVG(avg_reb) AS league_avg_rpg,
                AVG(avg_ast) AS league_avg_apg,
                AVG(avg_stl) AS league_avg_spg,
                AVG(avg_blk) AS league_avg_bpg,
                AVG(fg_pct) AS league_avg_fg_pct,
                AVG(fg3_pct) AS league_avg_fg3_pct,
                AVG(ft_pct) AS league_avg_ft_pct,
                AVG(avg_ts_pct) AS league_avg_ts_pct,
                AVG(avg_usg_pct) AS league_avg_usg_pct
            FROM agg_player_season
            WHERE gp >= 10
            GROUP BY season_year, season_type
        ),
        team_benchmarks AS (
            SELECT
                season_year,
                season_type,
                COUNT(DISTINCT team_id) AS total_teams,
                AVG(avg_pts) AS league_avg_team_ppg,
                AVG(avg_reb) AS league_avg_team_rpg,
                AVG(avg_ast) AS league_avg_team_apg,
                AVG(fg_pct) AS league_avg_team_fg_pct,
                AVG(fg3_pct) AS league_avg_team_fg3_pct
            FROM agg_team_season
            GROUP BY season_year, season_type
        )
        SELECT
            p.*,
            t.total_teams,
            t.league_avg_team_ppg,
            t.league_avg_team_rpg,
            t.league_avg_team_apg,
            t.league_avg_team_fg_pct,
            t.league_avg_team_fg3_pct
        FROM player_benchmarks p
        LEFT JOIN team_benchmarks t
            ON p.season_year = t.season_year
            AND p.season_type = t.season_type
    """
