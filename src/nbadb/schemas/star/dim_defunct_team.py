"""Pandera star-schema contract for dim_defunct_team."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimDefunctTeamSchema(BaseSchema):
    """Defunct franchise history from FranchiseHistory endpoint (result set 1)."""

    league_id: str = pa.Field(
        metadata={
            "source": "FranchiseHistory.DefunctTeams.LEAGUE_ID",
            "description": "League identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.TEAM_ID",
            "description": "Unique team identifier",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.TEAM_CITY",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.TEAM_NAME",
            "description": "Team name",
        },
    )
    start_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.START_YEAR",
            "description": "First year of franchise era",
        },
    )
    end_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.END_YEAR",
            "description": "Last year of franchise era",
        },
    )
    years: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.YEARS",
            "description": "Total years in franchise era",
        },
    )
    games: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.GAMES",
            "description": "Total games played",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.WINS",
            "description": "Total wins",
        },
    )
    losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.LOSSES",
            "description": "Total losses",
        },
    )
    win_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.WIN_PCT",
            "description": "Win percentage",
        },
    )
    po_appearances: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.PO_APPEARANCES",
            "description": "Playoff appearances count",
        },
    )
    div_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.DIV_TITLES",
            "description": "Division titles won",
        },
    )
    conf_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.CONF_TITLES",
            "description": "Conference titles won",
        },
    )
    league_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.DefunctTeams.LEAGUE_TITLES",
            "description": "League championships won",
        },
    )
