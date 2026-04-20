from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimArenaSchema(BaseSchema):
    arena_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.arena_id",
            "description": ("Surrogate arena identifier"),
        },
    )
    arena_name: str = pa.Field(
        metadata={
            "source": ("TeamDetails.TeamBackground.ARENA"),
            "description": "Arena name",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.city",
            "description": "Arena city",
        },
    )
    state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.state",
            "description": "Arena state",
        },
    )
    country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.country",
            "description": "Arena country",
        },
    )
