from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactDraftSchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("DraftHistory.DraftHistory.PERSON_ID"),
            "description": ("Drafted player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("DraftHistory.DraftHistory.TEAM_ID"),
            "description": ("Drafting team identifier"),
            "fk_ref": "dim_team.team_id",
        },
    )
    season: str = pa.Field(
        metadata={
            "source": ("DraftHistory.DraftHistory.SEASON"),
            "description": ("Draft season year"),
        },
    )
    round_number: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("DraftHistory.DraftHistory.ROUND_NUMBER"),
            "description": ("Draft round (1 or 2)"),
        },
    )
    round_pick: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("DraftHistory.DraftHistory.ROUND_PICK"),
            "description": ("Pick number within round"),
        },
    )
    overall_pick: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("DraftHistory.DraftHistory.OVERALL_PICK"),
            "description": "Overall pick number",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("DraftHistory.DraftHistory.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    organization: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("DraftHistory.DraftHistory.ORGANIZATION"),
            "description": ("College or organization"),
        },
    )
    organization_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("DraftHistory.DraftHistory.ORGANIZATION_TYPE"),
            "description": ("Type (College, HS, Intl, etc.)"),
        },
    )
    player_profile_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("DraftHistory.DraftHistory.PLAYER_PROFILE_FLAG"),
            "description": ("Has player profile (1=yes)"),
        },
    )
