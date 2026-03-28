from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season"
    depends_on: ClassVar[list[str]] = [
        "fact_player_game_traditional",
        "fact_player_game_advanced",
        "dim_game",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            t.player_id,
            t.team_id,
            tm.abbreviation AS team_abbreviation,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            SUM(t.min) AS total_min,
            AVG(t.min) AS avg_min,
            SUM(t.pts) AS total_pts, AVG(t.pts) AS avg_pts,
            SUM(t.reb) AS total_reb, AVG(t.reb) AS avg_reb,
            SUM(t.ast) AS total_ast, AVG(t.ast) AS avg_ast,
            SUM(t.stl) AS total_stl, AVG(t.stl) AS avg_stl,
            SUM(t.blk) AS total_blk, AVG(t.blk) AS avg_blk,
            SUM(t.tov) AS total_tov, AVG(t.tov) AS avg_tov,
            SUM(t.fgm) AS total_fgm, SUM(t.fga) AS total_fga,
            SUM(t.fgm)::FLOAT / NULLIF(SUM(t.fga), 0) AS fg_pct,
            SUM(t.fg3m) AS total_fg3m, SUM(t.fg3a) AS total_fg3a,
            SUM(t.fg3m)::FLOAT / NULLIF(SUM(t.fg3a), 0) AS fg3_pct,
            SUM(t.ftm) AS total_ftm, SUM(t.fta) AS total_fta,
            SUM(t.ftm)::FLOAT / NULLIF(SUM(t.fta), 0) AS ft_pct,
            AVG(a.off_rating) AS avg_off_rating,
            AVG(a.def_rating) AS avg_def_rating,
            AVG(a.net_rating) AS avg_net_rating,
            AVG(a.ts_pct) AS avg_ts_pct,
            AVG(a.usg_pct) AS avg_usg_pct,
            AVG(a.pie) AS avg_pie
        FROM fact_player_game_traditional t
        JOIN dim_game g ON t.game_id = g.game_id
        LEFT JOIN dim_team tm ON t.team_id = tm.team_id
        LEFT JOIN fact_player_game_advanced a
            ON t.game_id = a.game_id AND t.player_id = a.player_id
        GROUP BY t.player_id, t.team_id, tm.abbreviation, g.season_year, g.season_type
    """
