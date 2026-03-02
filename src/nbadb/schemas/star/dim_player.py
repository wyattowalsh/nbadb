from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimPlayerSchema(BaseSchema):
    player_sk: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.ROW_NUMBER",
            "description": ("Surrogate key for SCD2 player"),
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.PERSON_ID"),
            "description": ("Natural key — NBA player identifier"),
        },
    )
    full_name: str = pa.Field(
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.DISPLAY_FIRST_LAST"),
            "description": "Player full name",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.FIRST_NAME"),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.LAST_NAME"),
            "description": "Player last name",
        },
    )
    is_active: bool | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.ROSTER_STATUS"),
            "description": ("Whether player is active"),
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.TEAM_ID"),
            "description": "Current team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.POSITION"),
            "description": "Player position",
        },
    )
    jersey_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.JERSEY"),
            "description": "Jersey number",
        },
    )
    height: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.HEIGHT"),
            "description": "Player height",
        },
    )
    weight: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.WEIGHT"),
            "description": "Player weight in lbs",
        },
    )
    birth_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.BIRTHDATE"),
            "description": "Date of birth",
        },
    )
    country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.COUNTRY"),
            "description": "Country of origin",
        },
    )
    college_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "derived.college_id",
            "description": "College identifier",
            "fk_ref": ("dim_college.college_id"),
        },
    )
    draft_year: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.DRAFT_YEAR"),
            "description": "Draft year",
        },
    )
    draft_round: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.DRAFT_ROUND"),
            "description": "Draft round",
        },
    )
    draft_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.DRAFT_NUMBER"),
            "description": "Draft pick number",
        },
    )
    from_year: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.FROM_YEAR"),
            "description": ("First year in the league"),
        },
    )
    to_year: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.TO_YEAR"),
            "description": ("Last year in the league"),
        },
    )
    valid_from: str = pa.Field(
        metadata={
            "source": "derived.valid_from",
            "description": ("SCD2 valid-from season"),
        },
    )
    valid_to: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.valid_to",
            "description": ("SCD2 valid-to season"),
        },
    )
    is_current: bool = pa.Field(
        metadata={
            "source": "derived.is_current",
            "description": ("Whether this is the current record"),
        },
    )
