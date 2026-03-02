from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactTeamGameTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_team_game"
    depends_on: ClassVar[list[str]] = [
        "stg_box_score_traditional",
        "stg_line_score",
    ]

    _SQL: ClassVar[str] = """
        WITH team_agg AS (
            SELECT
                game_id, team_id,
                SUM(fgm) AS fgm, SUM(fga) AS fga,
                CASE WHEN SUM(fga) > 0
                     THEN SUM(fgm)::FLOAT / SUM(fga)
                     ELSE NULL END AS fg_pct,
                SUM(fg3m) AS fg3m, SUM(fg3a) AS fg3a,
                CASE WHEN SUM(fg3a) > 0
                     THEN SUM(fg3m)::FLOAT / SUM(fg3a)
                     ELSE NULL END AS fg3_pct,
                SUM(ftm) AS ftm, SUM(fta) AS fta,
                CASE WHEN SUM(fta) > 0
                     THEN SUM(ftm)::FLOAT / SUM(fta)
                     ELSE NULL END AS ft_pct,
                SUM(oreb) AS oreb, SUM(dreb) AS dreb,
                SUM(reb) AS reb,
                SUM(ast) AS ast, SUM(stl) AS stl,
                SUM(blk) AS blk, SUM(tov) AS tov,
                SUM(pf) AS pf, SUM(pts) AS pts
            FROM stg_box_score_traditional
            WHERE player_id IS NOT NULL
            GROUP BY game_id, team_id
        )
        SELECT
            t.*,
            l.pts_qtr1, l.pts_qtr2, l.pts_qtr3, l.pts_qtr4
        FROM team_agg t
        LEFT JOIN stg_line_score l
            ON t.game_id = l.game_id AND t.team_id = l.team_id
        ORDER BY t.game_id, t.team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
