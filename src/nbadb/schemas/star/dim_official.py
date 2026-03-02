from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimOfficialSchema(BaseSchema):
    official_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": ("ScoreboardV2.GameInfo.OFFICIAL_ID"),
            "description": ("Unique official identifier"),
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameInfo.FIRST_NAME"),
            "description": ("Official first name"),
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameInfo.LAST_NAME"),
            "description": ("Official last name"),
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameInfo.JERSEY_NUM"),
            "description": ("Official jersey number"),
        },
    )
