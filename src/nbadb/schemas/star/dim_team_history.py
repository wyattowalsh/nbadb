from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimTeamHistorySchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "FranchiseHistory"
                ".FranchiseHistory.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": (
                "Season year (e.g. 2024-25)"
            ),
            "fk_ref": (
                "dim_season.season_year"
            ),
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "FranchiseHistory"
                ".FranchiseHistory.TEAM_CITY"
            ),
            "description": (
                "Team city for season"
            ),
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "FranchiseHistory"
                ".FranchiseHistory.TEAM_NAME"
            ),
            "description": (
                "Team nickname for season"
            ),
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon"
                ".TeamInfoCommon"
                ".TEAM_ABBREVIATION"
            ),
            "description": (
                "Team abbreviation for season"
            ),
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "FranchiseHistory"
                ".FranchiseHistory.LEAGUE_ID"
            ),
            "description": "League identifier",
        },
    )
