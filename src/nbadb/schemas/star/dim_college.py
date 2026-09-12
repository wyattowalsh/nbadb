from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimCollegeSchema(BaseSchema):
    college_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.sha256_college_name_v1",
            "description": "Deterministic surrogate college identifier",
        },
    )
    college_name: str = pa.Field(
        unique=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.SCHOOL"),
            "description": "College name",
        },
    )
