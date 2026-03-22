from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerShootingSplitsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_shooting_splits_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_shoot_assisted_by",
        "stg_player_shoot_assisted_shot",
        "stg_player_shoot_overall",
        "stg_player_shoot_5ft",
        "stg_player_shoot_8ft",
        "stg_player_shoot_area",
        "stg_player_shoot_type",
        "stg_player_shoot_type_summary",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'assisted_by' AS shooting_split
        FROM stg_player_shoot_assisted_by
        UNION ALL BY NAME
        SELECT *, 'assisted_shot' AS shooting_split
        FROM stg_player_shoot_assisted_shot
        UNION ALL BY NAME
        SELECT *, 'overall' AS shooting_split
        FROM stg_player_shoot_overall
        UNION ALL BY NAME
        SELECT *, 'by_5ft' AS shooting_split
        FROM stg_player_shoot_5ft
        UNION ALL BY NAME
        SELECT *, 'by_8ft' AS shooting_split
        FROM stg_player_shoot_8ft
        UNION ALL BY NAME
        SELECT *, 'by_area' AS shooting_split
        FROM stg_player_shoot_area
        UNION ALL BY NAME
        SELECT *, 'by_type' AS shooting_split
        FROM stg_player_shoot_type
        UNION ALL BY NAME
        SELECT *, 'type_summary' AS shooting_split
        FROM stg_player_shoot_type_summary
    """
