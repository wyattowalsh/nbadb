from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactGameResultSchema(BaseSchema):
    game_id: str = pa.Field(
        unique=True,
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    game_date: str = pa.Field(
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.GAME_DATE"),
            "description": "Game date",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.SEASON_ID"),
            "description": ("Season type (Regular, Playoff)"),
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("derived.home_team_id"),
            "description": "Home team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("derived.visitor_team_id"),
            "description": ("Visiting team identifier"),
            "fk_ref": "dim_team.team_id",
        },
    )
    wl_home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.wl_home",
            "description": ("Home team win/loss (W or L)"),
        },
    )
    pts_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.pts_home",
            "description": "Home team points",
        },
    )
    pts_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.pts_away",
            "description": "Away team points",
        },
    )
    plus_minus_home: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.plus_minus_home",
            "description": ("Home team plus-minus"),
        },
    )
    plus_minus_away: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.plus_minus_away",
            "description": ("Away team plus-minus"),
        },
    )
    pts_qtr1_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR1_HOME"),
            "description": ("Home team Q1 points"),
        },
    )
    pts_qtr2_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR2_HOME"),
            "description": ("Home team Q2 points"),
        },
    )
    pts_qtr3_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR3_HOME"),
            "description": ("Home team Q3 points"),
        },
    )
    pts_qtr4_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR4_HOME"),
            "description": ("Home team Q4 points"),
        },
    )
    pts_ot1_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_OT1_HOME"),
            "description": ("Home team OT1 points"),
        },
    )
    pts_ot2_home: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_OT2_HOME"),
            "description": ("Home team OT2 points"),
        },
    )
    pts_qtr1_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR1_AWAY"),
            "description": ("Away team Q1 points"),
        },
    )
    pts_qtr2_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR2_AWAY"),
            "description": ("Away team Q2 points"),
        },
    )
    pts_qtr3_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR3_AWAY"),
            "description": ("Away team Q3 points"),
        },
    )
    pts_qtr4_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR4_AWAY"),
            "description": ("Away team Q4 points"),
        },
    )
    pts_ot1_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_OT1_AWAY"),
            "description": ("Away team OT1 points"),
        },
    )
    pts_ot2_away: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_OT2_AWAY"),
            "description": ("Away team OT2 points"),
        },
    )
