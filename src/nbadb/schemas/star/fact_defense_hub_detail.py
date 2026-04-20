from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactDefenseHubDetailSchema(BaseSchema):
    defense_metric: str = pa.Field(
        metadata={
            "source": "derived.defense_hub.metric",
            "description": "Normalized defense-hub metric discriminator",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "DefenseHub.*.RANK",
            "description": "Rank within the defense hub metric lane",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "DefenseHub.*.TEAM_ID",
            "description": "Team identifier when present",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "DefenseHub.*.TEAM_ABBREVIATION",
            "description": "Team abbreviation when present",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "DefenseHub.*.TEAM_NAME",
            "description": "Team display name when present",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the defense hub request",
        },
    )
    stat_value: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.defense_hub.stat_value",
            "description": "Metric value for the selected defense hub lane",
        },
    )
