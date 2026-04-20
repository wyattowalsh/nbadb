from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayoffPictureTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_playoff_picture"
    depends_on: ClassVar[list[str]] = [
        "stg_playoff_picture_east",
        "stg_playoff_picture_west",
        "stg_playoff_picture_east_standings",
        "stg_playoff_picture_west_standings",
        "stg_playoff_picture_east_remaining",
        "stg_playoff_picture_west_remaining",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'East' AS conference
        FROM stg_playoff_picture_east
        LEFT JOIN stg_playoff_picture_east_standings USING (team_id)
        LEFT JOIN stg_playoff_picture_east_remaining USING (team_id)
        UNION ALL BY NAME
        SELECT *, 'West' AS conference
        FROM stg_playoff_picture_west
        LEFT JOIN stg_playoff_picture_west_standings USING (team_id)
        LEFT JOIN stg_playoff_picture_west_remaining USING (team_id)
    """
