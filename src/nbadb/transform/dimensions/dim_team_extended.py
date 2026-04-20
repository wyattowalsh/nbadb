from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimTeamExtendedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_team_extended"
    depends_on: ClassVar[list[str]] = [
        "stg_team_details",
        "stg_team_info_common",
        "stg_team_years",
    ]

    _SQL: ClassVar[str] = """
        -- NOTE: SELECT * across JOINs; monitor for column collisions if staging schemas evolve
        SELECT d.*, c.* EXCLUDE (team_id), y.* EXCLUDE (team_id)
        FROM stg_team_details d
        JOIN stg_team_info_common c USING (team_id)
        LEFT JOIN stg_team_years y USING (team_id)
    """
