from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactHomepageDetailSchema(BaseSchema):
    homepage_metric: str = pa.Field(
        isin=["pts", "reb", "ast", "stl", "fg_pct", "ft_pct", "fg3_pct", "blk"],
        metadata={
            "source": "derived.homepage_metric",
            "description": "Homepage leaderboard metric discriminator",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "HomePageV2.HomePageStat*.RANK",
            "description": "Rank within the homepage leaderboard lane",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "HomePageV2.HomePageStat*.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": "HomePageV2.HomePageStat*.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": "HomePageV2.HomePageStat*.TEAM_NAME",
            "description": "Team display name",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the leaderboard request",
        },
    )
    stat_value: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "derived.homepage_v2.stat_value",
            "description": "Metric value for the selected homepage leaderboard lane",
        },
    )
