from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawShotChartDetailSchema(BaseSchema):
    grid_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".GRID_TYPE"
            ),
            "description": "Shot chart grid type",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_event_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".GAME_EVENT_ID"
            ),
            "description": "Event identifier within game",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".PERIOD"
            ),
            "description": "Game period number",
        },
    )
    minutes_remaining: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".MINUTES_REMAINING"
            ),
            "description": (
                "Minutes remaining in period"
            ),
        },
    )
    seconds_remaining: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SECONDS_REMAINING"
            ),
            "description": (
                "Seconds remaining in period"
            ),
        },
    )
    event_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".EVENT_TYPE"
            ),
            "description": (
                "Shot event type (Made/Missed)"
            ),
        },
    )
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".ACTION_TYPE"
            ),
            "description": (
                "Specific shot action type"
            ),
        },
    )
    shot_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_TYPE"
            ),
            "description": (
                "Shot type (2PT/3PT Field Goal)"
            ),
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_ZONE_BASIC"
            ),
            "description": "Basic shot zone category",
        },
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_ZONE_AREA"
            ),
            "description": "Shot zone area on court",
        },
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_ZONE_RANGE"
            ),
            "description": "Shot distance range bucket",
        },
    )
    shot_distance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_DISTANCE"
            ),
            "description": "Shot distance in feet",
        },
    )
    loc_x: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".LOC_X"
            ),
            "description": (
                "Shot X coordinate on court"
            ),
        },
    )
    loc_y: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".LOC_Y"
            ),
            "description": (
                "Shot Y coordinate on court"
            ),
        },
    )
    shot_attempted_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_ATTEMPTED_FLAG"
            ),
            "description": (
                "Flag indicating shot was attempted"
            ),
        },
    )
    shot_made_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".SHOT_MADE_FLAG"
            ),
            "description": (
                "Flag indicating shot was made"
            ),
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".GAME_DATE"
            ),
            "description": "Date of the game",
        },
    )
    htm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".HTM"
            ),
            "description": "Home team abbreviation",
        },
    )
    vtm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartDetail.Shot_Chart_Detail"
                ".VTM"
            ),
            "description": (
                "Visitor team abbreviation"
            ),
        },
    )


class RawShotChartLeagueWideSchema(BaseSchema):
    grid_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.GRID_TYPE"
            ),
            "description": "Shot chart grid type",
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.SHOT_ZONE_BASIC"
            ),
            "description": "Basic shot zone category",
        },
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.SHOT_ZONE_AREA"
            ),
            "description": "Shot zone area on court",
        },
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.SHOT_ZONE_RANGE"
            ),
            "description": "Shot distance range bucket",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.FGA"
            ),
            "description": "Field goals attempted",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ShotChartLeagueWide"
                ".League_Wide.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
