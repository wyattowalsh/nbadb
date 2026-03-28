from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgeGameTeamTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_game_team"
    depends_on: ClassVar[list[str]] = ["stg_league_game_log"]

    _SQL: ClassVar[str] = """
        SELECT DISTINCT
            game_id,
            home_team_id AS team_id,
            'home' AS side,
            wl_home AS wl,
            season_year
        FROM stg_league_game_log
        UNION ALL
        SELECT DISTINCT
            game_id,
            visitor_team_id AS team_id,
            'away' AS side,
            CASE WHEN wl_home = 'W' THEN 'L'
                 WHEN wl_home = 'L' THEN 'W'
                 ELSE NULL
            END AS wl,
            season_year
        FROM stg_league_game_log
    """
