from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggLineupEfficiencyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_lineup_efficiency"
    depends_on: ClassVar[list[str]] = ["fact_lineup_stats"]

    _SQL: ClassVar[str] = """
        SELECT
            group_id, team_id, season_year,
            SUM(gp) AS total_gp,
            SUM(min) AS total_min,
            SUM(pts)::FLOAT / NULLIF(SUM(min), 0) * 48.0 AS pts_per48,
            AVG(net_rating) AS avg_net_rating,
            SUM(plus_minus) AS total_plus_minus
        FROM fact_lineup_stats
        GROUP BY group_id, team_id, season_year
        ORDER BY season_year, avg_net_rating DESC
    """
