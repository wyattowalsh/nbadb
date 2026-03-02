from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactGameScoringTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_game_scoring"
    depends_on: ClassVar[list[str]] = ["stg_line_score"]

    _SQL: ClassVar[str] = """
        WITH home AS (
            SELECT game_id, team_id_home AS team_id, 'home' AS side,
                UNNEST([1,2,3,4,5,6]) AS period,
                UNNEST([
                    pts_qtr1_home, pts_qtr2_home,
                    pts_qtr3_home, pts_qtr4_home,
                    pts_ot1_home, pts_ot2_home
                ]) AS pts
            FROM stg_line_score
        ),
        away AS (
            SELECT game_id, team_id_away AS team_id, 'away' AS side,
                UNNEST([1,2,3,4,5,6]) AS period,
                UNNEST([
                    pts_qtr1_away, pts_qtr2_away,
                    pts_qtr3_away, pts_qtr4_away,
                    pts_ot1_away, pts_ot2_away
                ]) AS pts
            FROM stg_line_score
        )
        SELECT * FROM home WHERE pts IS NOT NULL
        UNION ALL
        SELECT * FROM away WHERE pts IS NOT NULL
        ORDER BY game_id, side, period
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
