from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimSeasonPhaseSchema(BaseSchema):
    phase_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.phase_id",
            "description": (
                "Season phase identifier"
            ),
        },
    )
    phase_name: str = pa.Field(
        metadata={
            "source": "derived.phase_name",
            "description": (
                "Phase name "
                "(e.g. Regular, Playoffs)"
            ),
        },
    )
    phase_order: int = pa.Field(
        gt=0,
        metadata={
            "source": "derived.phase_order",
            "description": (
                "Sort order of phase in season"
            ),
        },
    )
