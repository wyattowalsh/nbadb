from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggTeamPaceAndEfficiencyTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_team_pace_and_efficiency"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "fact_player_game_advanced",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH team_adv AS (
            SELECT
                a.team_id,
                g.game_id,
                g.season_year,
                g.season_type,
                AVG(a.pace) AS pace,
                AVG(a.off_rating) AS off_rating,
                AVG(a.def_rating) AS def_rating,
                AVG(a.net_rating) AS net_rating
            FROM fact_player_game_advanced a
            JOIN dim_game g ON a.game_id = g.game_id
            GROUP BY a.team_id, g.game_id, g.season_year, g.season_type
        )
        SELECT
            team_id,
            season_year,
            season_type,
            COUNT(*) AS gp,
            AVG(pace) AS avg_pace,
            AVG(off_rating) AS avg_ortg,
            AVG(def_rating) AS avg_drtg,
            AVG(net_rating) AS avg_net_rtg
        FROM team_adv
        GROUP BY team_id, season_year, season_type
        ORDER BY season_year, team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
