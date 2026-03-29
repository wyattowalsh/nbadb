from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayByPlayVideoSchema(BaseSchema):
    video_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayByPlayV3.AvailableVideo.VIDEO_AVAILABLE",
            "description": "Flag indicating whether video replay is available (0/1)",
        },
    )
