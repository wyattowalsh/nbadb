from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggTeamSeasonTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_team_season"
    depends_on: ClassVar[list[str]] = ["fact_team_game", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            t.team_id,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            AVG(t.pts) AS avg_pts,
            AVG(t.reb) AS avg_reb,
            AVG(t.ast) AS avg_ast,
            AVG(t.stl) AS avg_stl,
            AVG(t.blk) AS avg_blk,
            AVG(t.tov) AS avg_tov,
            SUM(t.fgm)::FLOAT / NULLIF(SUM(t.fga), 0) AS fg_pct,
            SUM(t.fg3m)::FLOAT / NULLIF(SUM(t.fg3a), 0) AS fg3_pct,
            SUM(t.ftm)::FLOAT / NULLIF(SUM(t.fta), 0) AS ft_pct
        FROM fact_team_game t
        JOIN dim_game g ON t.game_id = g.game_id
        GROUP BY t.team_id, g.season_year, g.season_type
        ORDER BY g.season_year, t.team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
