from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerAwardsSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.PERSON_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    description: str = pa.Field(
        metadata={
            "source": ("PlayerAwards.PlayerAwards.DESCRIPTION"),
            "description": ("Award description"),
        },
    )
    all_nba_team_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.ALL_NBA_TEAM_NUMBER"),
            "description": ("All-NBA team number"),
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.SEASON"),
            "description": "Award season",
        },
    )
    month: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.MONTH"),
            "description": ("Award month (if applicable)"),
        },
    )
    week: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.WEEK"),
            "description": ("Award week (if applicable)"),
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.CONFERENCE"),
            "description": ("Conference for award"),
        },
    )
    award_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.TYPE"),
            "description": ("Award type classification"),
        },
    )
    subtype1: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.SUBTYPE1"),
            "description": ("Award subtype 1"),
        },
    )
    subtype2: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.SUBTYPE2"),
            "description": ("Award subtype 2"),
        },
    )
    subtype3: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayerAwards.PlayerAwards.SUBTYPE3"),
            "description": ("Award subtype 3"),
        },
    )
