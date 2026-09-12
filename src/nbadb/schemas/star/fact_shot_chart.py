from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactShotChartSchema(BaseSchema):
    __consumer_metadata__ = {
        "grain": "shot-attempt-observation",
        "agent_intents": ["shot_chart", "shot_context", "shot_play_by_play_join"],
        "join_hints": {
            "dim_game": "game_id",
            "fact_play_by_play": "game_id + game_event_id with explicit 0/1/many match status",
        },
    }

    grid_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.GRID_TYPE",
            "description": "Provider shot-chart grid type",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.GAME_ID",
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    game_event_id: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.GAME_EVENT_ID",
            "description": "Provider event identifier within the game",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.PLAYER_ID",
            "description": "Player identifier",
            "fk_ref": ("dim_player.player_id"),
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.PLAYER_NAME",
            "description": "Provider player name observed with the shot",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.TEAM_NAME",
            "description": "Provider team name observed with the shot",
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "request.ShotChartDetail.LeagueID",
            "description": "League or competition identifier that scoped the provider request",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "request.ShotChartDetail.Season",
            "description": "Provider request season, with game-dimension fallback",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "request.ShotChartDetail.SeasonType",
            "description": "Provider request season type, with game-dimension fallback",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.PERIOD",
            "description": ("Game period (1-4 qtrs, 5+ OT)"),
        },
    )
    minutes_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.MINUTES_REMAINING",
            "description": ("Minutes remaining in period"),
        },
    )
    seconds_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SECONDS_REMAINING",
            "description": ("Seconds remaining in period"),
        },
    )
    event_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.EVENT_TYPE",
            "description": "Provider made/missed event label",
        },
    )
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.ACTION_TYPE",
            "description": ("Shot action type description"),
        },
    )
    shot_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_TYPE",
            "description": ("Shot type (2PT or 3PT)"),
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_BASIC",
            "description": "Shot zone basic area",
        },
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_AREA",
            "description": ("Shot zone directional area"),
        },
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_RANGE",
            "description": ("Shot zone distance range"),
        },
    )
    shot_distance: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_DISTANCE",
            "description": ("Shot distance in feet"),
        },
    )
    loc_x: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.LOC_X",
            "description": ("Shot X-coordinate on court"),
        },
    )
    loc_y: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.LOC_Y",
            "description": ("Shot Y-coordinate on court"),
        },
    )
    shot_attempted_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_ATTEMPTED_FLAG",
            "description": "Provider shot-attempt indicator",
        },
    )
    shot_made_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.SHOT_MADE_FLAG",
            "description": ("Shot made (1) or missed (0)"),
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.GAME_DATE",
            "description": "Provider game date, with dimension fallback",
        },
    )
    htm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.HTM",
            "description": "Home-team abbreviation",
        },
    )
    vtm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.Shot_Chart_Detail.VTM",
            "description": "Visitor-team abbreviation",
        },
    )
