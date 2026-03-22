from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggAllTimeLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_all_time_leaders"
    depends_on: ClassVar[list[str]] = [
        "stg_all_time",
        "stg_all_time_ast",
        "stg_all_time_blk",
        "stg_all_time_dreb",
        "stg_all_time_fg3a",
        "stg_all_time_fg3m",
        "stg_all_time_fg3_pct",
        "stg_all_time_fga",
        "stg_all_time_fgm",
        "stg_all_time_fg_pct",
        "stg_all_time_fta",
        "stg_all_time_ftm",
        "stg_all_time_ft_pct",
        "stg_all_time_gp",
        "stg_all_time_oreb",
        "stg_all_time_pf",
        "stg_all_time_pts",
        "stg_all_time_reb",
        "stg_all_time_stl",
        "stg_all_time_tov",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'combined' AS stat_category
        FROM stg_all_time
        UNION ALL BY NAME
        SELECT *, 'ast' AS stat_category FROM stg_all_time_ast
        UNION ALL BY NAME
        SELECT *, 'blk' AS stat_category FROM stg_all_time_blk
        UNION ALL BY NAME
        SELECT *, 'dreb' AS stat_category FROM stg_all_time_dreb
        UNION ALL BY NAME
        SELECT *, 'fg3a' AS stat_category FROM stg_all_time_fg3a
        UNION ALL BY NAME
        SELECT *, 'fg3m' AS stat_category FROM stg_all_time_fg3m
        UNION ALL BY NAME
        SELECT *, 'fg3_pct' AS stat_category FROM stg_all_time_fg3_pct
        UNION ALL BY NAME
        SELECT *, 'fga' AS stat_category FROM stg_all_time_fga
        UNION ALL BY NAME
        SELECT *, 'fgm' AS stat_category FROM stg_all_time_fgm
        UNION ALL BY NAME
        SELECT *, 'fg_pct' AS stat_category FROM stg_all_time_fg_pct
        UNION ALL BY NAME
        SELECT *, 'fta' AS stat_category FROM stg_all_time_fta
        UNION ALL BY NAME
        SELECT *, 'ftm' AS stat_category FROM stg_all_time_ftm
        UNION ALL BY NAME
        SELECT *, 'ft_pct' AS stat_category FROM stg_all_time_ft_pct
        UNION ALL BY NAME
        SELECT *, 'gp' AS stat_category FROM stg_all_time_gp
        UNION ALL BY NAME
        SELECT *, 'oreb' AS stat_category FROM stg_all_time_oreb
        UNION ALL BY NAME
        SELECT *, 'pf' AS stat_category FROM stg_all_time_pf
        UNION ALL BY NAME
        SELECT *, 'pts' AS stat_category FROM stg_all_time_pts
        UNION ALL BY NAME
        SELECT *, 'reb' AS stat_category FROM stg_all_time_reb
        UNION ALL BY NAME
        SELECT *, 'stl' AS stat_category FROM stg_all_time_stl
        UNION ALL BY NAME
        SELECT *, 'tov' AS stat_category FROM stg_all_time_tov
    """
