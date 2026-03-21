from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggOnOffSplitsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_on_off_splits"
    depends_on: ClassVar[list[str]] = [
        "stg_team_dashboard_on_off",
        "stg_on_off",
        "stg_player_on_details",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            'player' AS entity_type,
            player_id AS entity_id,
            team_id,
            season_year,
            on_off,
            gp, min, pts, reb, ast,
            off_rating, def_rating, net_rating
        FROM stg_on_off
        UNION ALL
        SELECT
            'team' AS entity_type,
            NULL AS entity_id,
            team_id,
            season_year,
            on_off,
            gp, min, pts, reb, ast,
            off_rating, def_rating, net_rating
        FROM stg_team_dashboard_on_off
        UNION ALL BY NAME
        SELECT
            'player_detail' AS entity_type,
            player_id AS entity_id,
            team_id,
            season_year,
            on_off,
            gp, min, pts, reb, ast,
            off_rating, def_rating, net_rating
        FROM stg_player_on_details
        ORDER BY season_year, entity_type, entity_id
    """
