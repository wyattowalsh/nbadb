from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactStandingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_standings"
    depends_on: ClassVar[list[str]] = ["stg_standings"]

    _SQL: ClassVar[str] = """
        SELECT
            team_id,
            season_year,
            COALESCE(season_type, 'Regular Season') AS season_type,
            conference,
            division,
            wins,
            losses,
            win_pct,
            conference_rank,
            division_rank,
            home_record,
            road_record,
            last_ten,
            streak
        FROM stg_standings
    """
