from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamFranchiseTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_franchise"
    depends_on: ClassVar[list[str]] = ["stg_franchise"]

    _SQL: ClassVar[str] = """
        SELECT
            *,
            end_year - start_year + 1 AS franchise_age_years,
            CASE WHEN games > 0
                 THEN ROUND(wins * 1.0 / games, 3)
                 ELSE NULL
            END AS computed_win_pct
        FROM stg_franchise
        ORDER BY franchise_age_years DESC NULLS LAST, team_id
    """
