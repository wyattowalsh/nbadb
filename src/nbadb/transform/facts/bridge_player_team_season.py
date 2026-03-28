from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgePlayerTeamSeasonTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_player_team_season"
    depends_on: ClassVar[list[str]] = ["stg_player_info"]

    _SQL: ClassVar[str] = """
        SELECT DISTINCT
            player_id,
            team_id,
            season AS season_year,
            jersey_number,
            position
        FROM stg_player_info
        WHERE player_id IS NOT NULL AND team_id IS NOT NULL
    """
