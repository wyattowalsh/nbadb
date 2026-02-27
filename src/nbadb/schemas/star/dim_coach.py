from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimCoachSchema(BaseSchema):
    coach_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.COACH_ID"
            ),
            "description": (
                "Unique coach identifier"
            ),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.SEASON"
            ),
            "description": (
                "Season year (e.g. 2024-25)"
            ),
            "fk_ref": (
                "dim_season.season_year"
            ),
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.FIRST_NAME"
            ),
            "description": "Coach first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.LAST_NAME"
            ),
            "description": "Coach last name",
        },
    )
    coach_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamRoster"
                ".Coaches.COACH_TYPE"
            ),
            "description": (
                "Coach type (Head Coach, etc.)"
            ),
        },
    )
    is_assistant: bool | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.is_assistant",
            "description": (
                "Whether coach is assistant"
            ),
        },
    )
