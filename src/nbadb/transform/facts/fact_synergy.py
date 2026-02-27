from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactSynergyTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_synergy"
    depends_on: ClassVar[list[str]] = ["stg_synergy"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, team_id, season_year,
            entity_type,
            play_type, type_grouping,
            gp, poss, ppp, pts,
            fgm, fga, fg_pct, efg_pct,
            ft_poss_pct, tov_poss_pct,
            sf_poss_pct, score_poss_pct,
            percentile
        FROM stg_synergy
        ORDER BY season_year, entity_type, player_id, play_type
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_synergy", staging["stg_synergy"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
