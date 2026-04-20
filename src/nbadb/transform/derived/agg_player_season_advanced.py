from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonAdvancedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season_advanced"
    depends_on: ClassVar[list[str]] = ["fact_player_game_advanced", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            a.player_id,
            a.team_id,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            AVG(a.off_rating) AS avg_off_rating,
            AVG(a.def_rating) AS avg_def_rating,
            AVG(a.net_rating) AS avg_net_rating,
            AVG(a.ts_pct) AS avg_ts_pct,
            AVG(a.usg_pct) AS avg_usg_pct,
            AVG(a.efg_pct) AS avg_efg_pct,
            AVG(a.ast_pct) AS avg_ast_pct,
            AVG(a.ast_ratio) AS avg_ast_ratio,
            AVG(a.oreb_pct) AS avg_oreb_pct,
            AVG(a.dreb_pct) AS avg_dreb_pct,
            AVG(a.reb_pct) AS avg_reb_pct,
            AVG(a.tov_pct) AS avg_tov_pct,
            AVG(a.pace) AS avg_pace,
            AVG(a.pie) AS avg_pie
        FROM fact_player_game_advanced a
        JOIN dim_game g ON a.game_id = g.game_id
        GROUP BY a.player_id, a.team_id, g.season_year, g.season_type
    """
