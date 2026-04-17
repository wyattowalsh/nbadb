from __future__ import annotations

from nbadb.transform.base import make_passthrough

FactVideoDetailsTransformer = make_passthrough("fact_video_details", "stg_video_details")
FactVideoDetailsAssetTransformer = make_passthrough(
    "fact_video_details_asset",
    "stg_video_details_asset",
)
FactVideoEventsTransformer = make_passthrough("fact_video_events", "stg_video_events")
FactVideoEventsAssetTransformer = make_passthrough(
    "fact_video_events_asset",
    "stg_video_events_asset",
)
FactVideoStatusTransformer = make_passthrough("fact_video_status", "stg_video_status")
