from __future__ import annotations

from nbadb.transform.base import make_passthrough

FactPlayByPlayV2Transformer = make_passthrough("fact_play_by_play_v2", "stg_play_by_play_v2")
FactPlayByPlayV2VideoTransformer = make_passthrough(
    "fact_play_by_play_v2_video",
    "stg_play_by_play_v2_video_available",
)
