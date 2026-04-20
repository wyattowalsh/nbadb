from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimTeamSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "CommonTeamYears.CommonTeamYears.TEAM_ID",
            "description": "NBA team identifier",
        },
    )
    abbreviation: str = pa.Field(
        metadata={
            "source": "CommonTeamYears.CommonTeamYears.ABBREVIATION",
            "description": "Team abbreviation (e.g. LAL)",
        },
    )
    full_name: str = pa.Field(
        metadata={
            "source": "derived.full_name",
            "description": "Full team name",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamDetails.TeamBackground.CITY",
            "description": "Team city",
        },
    )
    state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamDetails.TeamBackground.STATE",
            "description": "Team state",
        },
    )
    arena: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamDetails.TeamBackground.ARENA",
            "description": "Home arena name",
        },
    )
    year_founded: int | None = pa.Field(
        nullable=True,
        gt=1900,
        metadata={
            "source": "CommonTeamYears.CommonTeamYears.MIN_YEAR",
            "description": "Year team was founded",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamDetails.TeamBackground.CONFERENCE",
            "description": "Conference (East/West)",
        },
    )
    division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamDetails.TeamBackground.DIVISION",
            "description": "Division name",
        },
    )
