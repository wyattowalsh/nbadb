from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimSeasonPhaseSchema(BaseSchema):
    # NOTE: standalone lookup table — no FK refs in current star schema.
    # Kept as a reference dimension for ad-hoc queries and Kaggle exports.
    phase_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.phase_id",
            "description": ("Season phase identifier"),
        },
    )
    phase_name: str = pa.Field(
        metadata={
            "source": "derived.phase_name",
            "description": ("Phase name (e.g. Regular, Playoffs)"),
        },
    )
    phase_order: int = pa.Field(
        gt=0,
        metadata={
            "source": "derived.phase_order",
            "description": ("Sort order of phase in season"),
        },
    )
