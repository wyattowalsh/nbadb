from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayByPlayVideoTransformer(SqlTransformer):
    """Captures the video availability flag from PlayByPlayV3's AvailableVideo result set (index 1).

    The upstream API result set contains only VIDEO_AVAILABLE — no game_id,
    event_num, or other join keys — so the table is intentionally narrow.
    Per-event video availability is already captured in fact_play_by_play from
    the main result set (index 0).

    The staging key stg_play_by_play_video_available is excluded from model
    coverage checks in endpoint_coverage.py because it serves as a
    landing-completeness flag, not a joinable fact.
    """

    output_table: ClassVar[str] = "fact_play_by_play_video"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play_video_available"]

    _SQL: ClassVar[str] = """
        SELECT
            video_available
        FROM stg_play_by_play_video_available
    """
