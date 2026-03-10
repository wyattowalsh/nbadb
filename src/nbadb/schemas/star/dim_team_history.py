from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimTeamHistorySchema(BaseSchema):
    team_history_sk: int = pa.Field(
        gt=0,
        unique=True,
        metadata={
            "source": "derived.ROW_NUMBER",
            "description": "Surrogate key for SCD2 versioning",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "FranchiseHistory.FranchiseHistory.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.TEAM_CITY",
            "description": "Team city for this version",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.TEAM_NAME",
            "description": "Team nickname for this version",
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.TEAM_ABBREVIATION",
            "description": "Team abbreviation for this version",
        },
    )
    franchise_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.FranchiseHistory.TEAM_NAME",
            "description": "Franchise name",
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "FranchiseHistory.FranchiseHistory.LEAGUE_ID",
            "description": "League identifier",
        },
    )
    valid_from: str = pa.Field(
        metadata={
            "source": "derived.valid_from",
            "description": "Season when this version became active",
        },
    )
    valid_to: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.valid_to",
            "description": "Season of next change; NULL = current",
        },
    )
    is_current: bool = pa.Field(
        metadata={
            "source": "derived.is_current",
            "description": "TRUE if this is the current version",
        },
    )
