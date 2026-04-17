from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(literal_fields={"leader_source"})
class FactHomepageLeadersSchema(BaseSchema):
    leader_source: str = pa.Field(
        isin=["home_page", "homepage"],
        metadata={
            "description": "Alias source of the homepage leaders packet",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "description": "Rank within the homepage leaders packet",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Team display name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Team abbreviation",
        },
    )
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    ts_pct: float | None = pa.Field(nullable=True, ge=0.0)
    pts_per48: float | None = pa.Field(nullable=True, ge=0.0)
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Season type used for the leaders request",
        },
    )
