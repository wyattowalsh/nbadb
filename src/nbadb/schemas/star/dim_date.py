from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimDateSchema(BaseSchema):
    date_key: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.YYYYMMDD",
            "description": (
                "Integer date key YYYYMMDD"
            ),
        },
    )
    full_date: str = pa.Field(
        metadata={
            "source": "derived.full_date",
            "description": "Calendar date string",
        },
    )
    year: int = pa.Field(
        metadata={
            "source": "derived.year",
            "description": "Calendar year",
        },
    )
    month: int = pa.Field(
        ge=1,
        le=12,
        metadata={
            "source": "derived.month",
            "description": (
                "Calendar month (1-12)"
            ),
        },
    )
    day: int = pa.Field(
        ge=1,
        le=31,
        metadata={
            "source": "derived.day",
            "description": "Day of month (1-31)",
        },
    )
    day_of_week: int = pa.Field(
        ge=0,
        le=6,
        metadata={
            "source": "derived.day_of_week",
            "description": (
                "Day of week (0=Mon, 6=Sun)"
            ),
        },
    )
    day_name: str = pa.Field(
        metadata={
            "source": "derived.day_name",
            "description": (
                "Day name (Monday-Sunday)"
            ),
        },
    )
    month_name: str = pa.Field(
        metadata={
            "source": "derived.month_name",
            "description": (
                "Month name (January-December)"
            ),
        },
    )
    is_weekend: bool = pa.Field(
        metadata={
            "source": "derived.is_weekend",
            "description": (
                "Whether date is Saturday/Sunday"
            ),
        },
    )
    nba_season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.nba_season",
            "description": (
                "NBA season (e.g. 2024-25)"
            ),
        },
    )
    nba_phase: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.nba_phase",
            "description": (
                "NBA season phase name"
            ),
        },
    )
