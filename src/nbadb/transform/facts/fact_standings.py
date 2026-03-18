from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactStandingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_standings"
    depends_on: ClassVar[list[str]] = ["stg_standings", "stg_scoreboard"]

    _SQL: ClassVar[str] = """
        SELECT
            s.team_id,
            s.season_year,
            COALESCE(s.season_type, 'Regular Season') AS season_type,
            s.conference,
            s.division,
            s.wins,
            s.losses,
            s.win_pct,
            s.conference_rank,
            s.division_rank,
            s.home_record,
            s.road_record,
            s.last_ten,
            s.streak,
            sb.game_date AS standings_date
        FROM stg_standings s
        LEFT JOIN stg_scoreboard sb ON s.team_id = sb.team_id
            AND s.season_year = sb.season_year
        ORDER BY s.season_year, s.season_type, s.conference_rank
    """
