from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerClutchDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_clutch_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_clutch_last10sec_3pt2",
        "stg_player_clutch_last10sec_3pt",
        "stg_player_clutch_last1min_5pt",
        "stg_player_clutch_last1min_pm5",
        "stg_player_clutch_last30sec_3pt2",
        "stg_player_clutch_last30sec_3pt",
        "stg_player_clutch_last3min_5pt",
        "stg_player_clutch_last3min_pm5",
        "stg_player_clutch_last5min_5pt",
        "stg_player_clutch_last5min_pm5",
        "stg_player_clutch_overall",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'last10sec_3pt2' AS clutch_window
        FROM stg_player_clutch_last10sec_3pt2
        UNION ALL BY NAME
        SELECT *, 'last10sec_3pt' AS clutch_window
        FROM stg_player_clutch_last10sec_3pt
        UNION ALL BY NAME
        SELECT *, 'last1min_5pt' AS clutch_window
        FROM stg_player_clutch_last1min_5pt
        UNION ALL BY NAME
        SELECT *, 'last1min_pm5' AS clutch_window
        FROM stg_player_clutch_last1min_pm5
        UNION ALL BY NAME
        SELECT *, 'last30sec_3pt2' AS clutch_window
        FROM stg_player_clutch_last30sec_3pt2
        UNION ALL BY NAME
        SELECT *, 'last30sec_3pt' AS clutch_window
        FROM stg_player_clutch_last30sec_3pt
        UNION ALL BY NAME
        SELECT *, 'last3min_5pt' AS clutch_window
        FROM stg_player_clutch_last3min_5pt
        UNION ALL BY NAME
        SELECT *, 'last3min_pm5' AS clutch_window
        FROM stg_player_clutch_last3min_pm5
        UNION ALL BY NAME
        SELECT *, 'last5min_5pt' AS clutch_window
        FROM stg_player_clutch_last5min_5pt
        UNION ALL BY NAME
        SELECT *, 'last5min_pm5' AS clutch_window
        FROM stg_player_clutch_last5min_pm5
        UNION ALL BY NAME
        SELECT *, 'overall' AS clutch_window
        FROM stg_player_clutch_overall
    """
