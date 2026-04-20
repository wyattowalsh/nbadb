from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactLeadersTilesDetailSchema(BaseSchema):
    tile_variant: str = pa.Field(
        isin=["all_time_high", "last_season_high", "main", "low_season_high"],
        metadata={
            "source": "derived.leaders_tiles.variant",
            "description": "Leaders tiles result-set variant",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "LeadersTiles.*.RANK",
            "description": "Rank when the tile variant is ranked",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "LeadersTiles.*.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": "LeadersTiles.*.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": "LeadersTiles.*.TEAM_NAME",
            "description": "Team display name",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeadersTiles.*.SEASON_YEAR",
            "description": "Season year attached to historical tile variants",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the leaders tiles request",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeadersTiles.*.PTS",
            "description": "Points value surfaced by the tile variant",
        },
    )
