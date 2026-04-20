from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactDefenseHubSchema(BaseSchema):
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "DefenseHub.DefenseHubStat1.RANK",
            "description": "Rank within the base defense-hub packet",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "DefenseHub.DefenseHubStat1.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": "DefenseHub.DefenseHubStat1.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": "DefenseHub.DefenseHubStat1.TEAM_NAME",
            "description": "Team display name",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "DefenseHub.DefenseHubStat1.DREB",
            "description": "Defensive rebounds value from the base defense-hub packet",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the defense-hub request",
        },
    )
