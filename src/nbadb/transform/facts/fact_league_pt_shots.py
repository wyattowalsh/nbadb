from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeaguePtShotsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_pt_shots"
    depends_on: ClassVar[list[str]] = [
        "stg_league_pt_stats",
        "stg_league_pt_team_defend",
        "stg_league_team_pt_shot",
        "stg_league_opp_pt_shot",
        "stg_league_player_pt_shot",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'stats' AS shot_type
        FROM stg_league_pt_stats
        UNION ALL BY NAME
        SELECT *, 'team_defend' AS shot_type
        FROM stg_league_pt_team_defend
        UNION ALL BY NAME
        SELECT *, 'team' AS shot_type
        FROM stg_league_team_pt_shot
        UNION ALL BY NAME
        SELECT *, 'opponent' AS shot_type
        FROM stg_league_opp_pt_shot
        UNION ALL BY NAME
        SELECT *, 'player' AS shot_type
        FROM stg_league_player_pt_shot
    """
