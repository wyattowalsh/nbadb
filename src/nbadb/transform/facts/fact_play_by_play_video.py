from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayByPlayVideoTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_play_by_play_video"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play_video_available"]

    _SQL: ClassVar[str] = """
        SELECT
            video_available
        FROM stg_play_by_play_video_available
    """
