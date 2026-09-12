from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimSeasonSchema(BaseSchema):
    season_year: str = pa.Field(
        unique=True,
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.SEASON_ID"),
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    start_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.start_date",
            "description": ("First game date of season"),
        },
    )
    end_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.end_date",
            "description": ("Last game date of season"),
        },
    )
