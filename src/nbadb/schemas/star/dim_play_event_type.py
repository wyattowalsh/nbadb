from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimPlayEventTypeSchema(BaseSchema):
    event_type_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": ("derived.event_type_id"),
            "description": ("Play event type identifier"),
        },
    )
    event_type_name: str = pa.Field(
        metadata={
            "source": ("derived.event_type_name"),
            "description": ("Event type name (e.g. made_shot)"),
        },
    )
