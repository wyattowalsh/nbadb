from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactShotChartSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.PLAYER_ID"),
            "description": "Player identifier",
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    period: int = pa.Field(
        gt=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.PERIOD"),
            "description": ("Game period (1-4 qtrs, 5+ OT)"),
        },
    )
    minutes_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.MINUTES_REMAINING"),
            "description": ("Minutes remaining in period"),
        },
    )
    seconds_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SECONDS_REMAINING"),
            "description": ("Seconds remaining in period"),
        },
    )
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.ACTION_TYPE"),
            "description": ("Shot action type description"),
        },
    )
    shot_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_TYPE"),
            "description": ("Shot type (2PT or 3PT)"),
        },
    )
    zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_ZONE_BASIC"),
            "description": "Shot zone basic area",
        },
    )
    zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_ZONE_AREA"),
            "description": ("Shot zone directional area"),
        },
    )
    zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_ZONE_RANGE"),
            "description": ("Shot zone distance range"),
        },
    )
    shot_distance: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_DISTANCE"),
            "description": ("Shot distance in feet"),
        },
    )
    loc_x: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.LOC_X"),
            "description": ("Shot X-coordinate on court"),
        },
    )
    loc_y: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.LOC_Y"),
            "description": ("Shot Y-coordinate on court"),
        },
    )
    shot_made_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("ShotChartDetail.ShotChartDetail.SHOT_MADE_FLAG"),
            "description": ("Shot made (1) or missed (0)"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
