"""Pandera star-schema contract for dim_season_week."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimSeasonWeekSchema(BaseSchema):
    """Season week calendar from ScheduleLeagueV2 endpoint (result set 1)."""

    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.Weeks.SEASON_ID",
            "description": "Season identifier",
        },
    )
    week_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.Weeks.WEEK_NUMBER",
            "description": "Week number within the season",
        },
    )
    start_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.Weeks.START_DATE",
            "description": "Week start date",
        },
    )
    end_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.Weeks.END_DATE",
            "description": "Week end date",
        },
    )
