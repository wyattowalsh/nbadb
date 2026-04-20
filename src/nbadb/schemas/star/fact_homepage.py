from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactHomepageSchema(BaseSchema):
    homepage_source: str = pa.Field(
        isin=["home_page", "homepage"],
        metadata={
            "source": "derived.homepage_source",
            "description": "Alias source of the homepage packet",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "HomePageV2.HomePageStat1.RANK",
            "description": "Rank within the homepage points packet",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "HomePageV2.HomePageStat1.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": "HomePageV2.HomePageStat1.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": "HomePageV2.HomePageStat1.TEAM_NAME",
            "description": "Team display name",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "HomePageV2.HomePageStat1.PTS",
            "description": "Points value from the base homepage packet",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type used for the homepage request",
        },
    )
