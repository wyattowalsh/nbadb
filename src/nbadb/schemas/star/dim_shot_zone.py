from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimShotZoneSchema(BaseSchema):
    zone_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.zone_id",
            "description": ("Surrogate shot zone identifier"),
        },
    )
    shot_zone_basic: str = pa.Field(
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_BASIC"),
            "description": "Basic zone name",
        },
    )
    shot_zone_area: str = pa.Field(
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_AREA"),
            "description": ("Zone area (e.g. Left Side)"),
        },
    )
    shot_zone_range: str = pa.Field(
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_RANGE"),
            "description": ("Zone range (e.g. 16-24 ft.)"),
        },
    )
