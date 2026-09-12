from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimArenaSchema(BaseSchema):
    arena_id: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.sha256_arena_name_city_v1",
            "description": "Deterministic surrogate arena identifier",
        },
    )
    arena_name: str = pa.Field(
        metadata={
            "source": "derived.arena_name",
            "description": "Arena name",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.arena_city",
            "description": "Arena city",
        },
    )
    state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.ArenaInfo.arenaState",
            "description": "Arena state",
        },
    )
    country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.ArenaInfo.arenaCountry",
            "description": "Arena country",
        },
    )
    timezone: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.ArenaInfo.arenaTimezone",
            "description": "Arena timezone",
        },
    )
