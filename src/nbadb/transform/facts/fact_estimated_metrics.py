from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayerEstimatedMetricsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_estimated_metrics"
    depends_on: ClassVar[list[str]] = ["stg_player_tracking"]

    _SQL: ClassVar[str] = """
        SELECT
            p.player_id,
            p.team_id,
            p.gp,
            p.w,
            p.l,
            p.min,
            p.e_off_rating,
            p.e_def_rating,
            p.e_net_rating,
            p.e_pace,
            p.e_ast_ratio,
            p.e_oreb_pct,
            p.e_dreb_pct,
            p.e_reb_pct,
            p.e_tov_pct,
            p.e_usg_pct,
            p.season_year
        FROM stg_player_tracking p
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()


class FactTeamEstimatedMetricsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_team_estimated_metrics"
    depends_on: ClassVar[list[str]] = ["stg_team_dashboard_estimated"]

    _SQL: ClassVar[str] = """
        SELECT
            t.team_id,
            t.gp,
            t.w,
            t.l,
            t.min,
            t.e_off_rating,
            t.e_def_rating,
            t.e_net_rating,
            t.e_pace,
            t.e_ast_ratio,
            t.e_oreb_pct,
            t.e_dreb_pct,
            t.e_reb_pct,
            t.e_tov_pct,
            t.season_year
        FROM stg_team_dashboard_estimated t
        ORDER BY season_year, team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
