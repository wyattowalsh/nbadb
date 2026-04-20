"""Pandera star-schema contract for dim_all_players."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimAllPlayersSchema(BaseSchema):
    """All players directory from CommonAllPlayers endpoint."""

    person_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.PERSON_ID",
            "description": "Unique player identifier",
        },
    )
    display_last_comma_first: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.DISPLAY_LAST_COMMA_FIRST",
            "description": "Player name as Last, First",
        },
    )
    display_first_last: str = pa.Field(
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.DISPLAY_FIRST_LAST",
            "description": "Player name as First Last",
        },
    )
    roster_status: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.ROSTER_STATUS",
            "description": "Active roster flag (0 or 1)",
        },
    )
    from_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.FROM_YEAR",
            "description": "First year in the league",
        },
    )
    to_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TO_YEAR",
            "description": "Last year in the league",
        },
    )
    playercode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.PLAYERCODE",
            "description": "Player code slug",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TEAM_CITY",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.TEAM_CODE",
            "description": "Team code slug",
        },
    )
    games_played_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "CommonAllPlayers.CommonAllPlayers.GAMES_PLAYED_FLAG",
            "description": "Flag indicating games played",
        },
    )
