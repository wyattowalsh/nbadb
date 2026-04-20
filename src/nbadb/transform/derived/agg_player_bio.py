from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerBioTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_bio"
    depends_on: ClassVar[list[str]] = ["stg_league_player_bio"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_player_bio
    """
