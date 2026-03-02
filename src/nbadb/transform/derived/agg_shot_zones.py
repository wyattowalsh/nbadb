from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggShotZonesTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_shot_zones"
    depends_on: ClassVar[list[str]] = ["fact_shot_chart", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            s.player_id,
            g.season_year,
            s.zone_basic,
            s.zone_area,
            s.zone_range,
            COUNT(*) AS attempts,
            SUM(s.shot_made_flag) AS makes,
            SUM(s.shot_made_flag)::FLOAT / NULLIF(COUNT(*), 0) AS fg_pct,
            AVG(s.shot_distance) AS avg_distance
        FROM fact_shot_chart s
        JOIN dim_game g ON s.game_id = g.game_id
        GROUP BY s.player_id, g.season_year,
                 s.zone_basic, s.zone_area, s.zone_range
        ORDER BY g.season_year, s.player_id, s.zone_basic
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
