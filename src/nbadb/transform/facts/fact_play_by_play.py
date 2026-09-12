from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayByPlayTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_play_by_play"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play"]

    _SQL: ClassVar[str] = """
        SELECT
            *,
            COALESCE(action_type, 'unknown') AS event_type_name
        FROM stg_play_by_play
    """
