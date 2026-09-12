from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartLeagueAveragesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart_league_averages"
    depends_on: ClassVar[list[str]] = [
        "stg_shot_chart_league_averages",
        "stg_shot_chart_lineup_league_avg",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            grid_type,
            season_year,
            season_type,
            league_id,
            shot_zone_basic,
            shot_zone_area,
            shot_zone_range,
            fga,
            fgm,
            fg_pct,
            'shot_chart_detail' AS average_source
        FROM stg_shot_chart_league_averages
        UNION ALL BY NAME
        SELECT
            grid_type,
            season_year,
            season_type,
            league_id,
            shot_zone_basic,
            shot_zone_area,
            shot_zone_range,
            fga,
            fgm,
            fg_pct,
            'shot_chart_lineup_detail' AS average_source
        FROM stg_shot_chart_lineup_league_avg
    """
