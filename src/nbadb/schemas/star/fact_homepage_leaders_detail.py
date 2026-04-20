from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactHomepageLeadersDetailSchema(BaseSchema):
    leader_variant: str = pa.Field(
        isin=["main", "league_avg", "league_max"],
        metadata={
            "source": "derived.homepage_leaders.variant",
            "description": "Homepage leaders result-set variant",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "HomePageLeaders.HomePageLeaders.RANK",
            "description": "Rank within the primary homepage leaders packet",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "HomePageLeaders.HomePageLeaders.TEAM_ID",
            "description": "Team identifier when the variant is team-scoped",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "HomePageLeaders.HomePageLeaders.TEAM_ABBREVIATION",
            "description": "Team abbreviation when present",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "HomePageLeaders.HomePageLeaders.TEAM_NAME",
            "description": "Team name when present",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the leaders request",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.PTS",
            "description": "Points value for the variant",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.FG_PCT",
            "description": "Field goal percentage for the variant",
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.FG3_PCT",
            "description": "Three-point percentage for the variant",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.FT_PCT",
            "description": "Free throw percentage for the variant",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.EFG_PCT",
            "description": "Effective field goal percentage for the variant",
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.TS_PCT",
            "description": "True shooting percentage for the variant",
        },
    )
    pts_per48: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageLeaders.*.PTS_PER48",
            "description": "Points per 48 minutes for the variant",
        },
    )
