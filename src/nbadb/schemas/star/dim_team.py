from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimTeamSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.id",
            "description": "NBA team identifier",
        },
    )
    abbreviation: str = pa.Field(
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.abbreviation",
            "description": "Team abbreviation (e.g. LAL)",
        },
    )
    full_name: str = pa.Field(
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.full_name",
            "description": "Full team name",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.city",
            "description": "Team city",
        },
    )
    state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.state",
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
            "source": "nba_api.stats.static.teams.get_teams.year_founded",
            "description": "Year team was founded",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.TEAM_CONFERENCE",
            "description": "Conference (East/West)",
        },
    )
    division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.TEAM_DIVISION",
            "description": "Division name",
        },
    )
