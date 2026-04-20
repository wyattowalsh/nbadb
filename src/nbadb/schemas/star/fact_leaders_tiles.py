from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactLeadersTilesSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "LeadersTiles.AllTimeSeasonHigh.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": "LeadersTiles.AllTimeSeasonHigh.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": "LeadersTiles.AllTimeSeasonHigh.TEAM_NAME",
            "description": "Team display name",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeadersTiles.AllTimeSeasonHigh.SEASON_YEAR",
            "description": "Season year attached to the base leaders-tiles packet",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeadersTiles.AllTimeSeasonHigh.PTS",
            "description": "Points value from the base leaders-tiles packet",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the leaders-tiles request",
        },
    )
