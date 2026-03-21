from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactScoreboardDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_scoreboard",
        "stg_scoreboard_east_conf",
        "stg_scoreboard_west_conf",
        "stg_scoreboard_last_meeting",
        "stg_scoreboard_line_score",
        "stg_scoreboard_series_standings",
        "stg_scoreboard_v2_series_standings",
        "stg_scoreboard_team_leaders",
        "stg_scoreboard_ticket_links",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'available' AS detail_type
        FROM stg_scoreboard
        UNION ALL BY NAME
        SELECT *, 'east_conf_standings' AS detail_type
        FROM stg_scoreboard_east_conf
        UNION ALL BY NAME
        SELECT *, 'west_conf_standings' AS detail_type
        FROM stg_scoreboard_west_conf
        UNION ALL BY NAME
        SELECT *, 'last_meeting' AS detail_type
        FROM stg_scoreboard_last_meeting
        UNION ALL BY NAME
        SELECT *, 'line_score' AS detail_type
        FROM stg_scoreboard_line_score
        UNION ALL BY NAME
        SELECT *, 'series_standings' AS detail_type
        FROM stg_scoreboard_series_standings
        UNION ALL BY NAME
        SELECT *, 'v2_series_standings' AS detail_type
        FROM stg_scoreboard_v2_series_standings
        UNION ALL BY NAME
        SELECT *, 'team_leaders' AS detail_type
        FROM stg_scoreboard_team_leaders
        UNION ALL BY NAME
        SELECT *, 'ticket_links' AS detail_type
        FROM stg_scoreboard_ticket_links
    """
