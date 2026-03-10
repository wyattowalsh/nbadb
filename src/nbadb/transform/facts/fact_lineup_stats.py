from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLineupStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_lineup_stats"
    depends_on: ClassVar[list[str]] = ["stg_lineup"]

    _SQL: ClassVar[str] = """
        SELECT
            group_id, team_id, season_year,
            gp, min,
            fgm, fga, fg_pct,
            fg3m, fg3a, fg3_pct,
            ftm, fta, ft_pct,
            oreb, dreb, reb,
            ast, stl, blk, tov, pf, pts,
            plus_minus, net_rating
        FROM stg_lineup
        ORDER BY season_year, team_id, min DESC
    """
