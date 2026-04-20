from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactMatchupTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_matchup"
    depends_on: ClassVar[list[str]] = ["stg_matchup"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id,
            off_player_id, def_player_id,
            off_team_id, def_team_id,
            matchup_min, partial_poss,
            player_pts,
            def_fgm, def_fga, def_fg_pct
        FROM stg_matchup
    """
