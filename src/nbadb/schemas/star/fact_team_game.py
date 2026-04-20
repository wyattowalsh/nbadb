from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactTeamGameSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.fgm",
            "description": ("Team field goals made"),
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.fga",
            "description": ("Team field goals attempted"),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.team_agg.fg_pct",
            "description": ("Team field goal percentage"),
        },
    )
    fg3m: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.fg3m",
            "description": ("Team three-pointers made"),
        },
    )
    fg3a: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.fg3a",
            "description": ("Team three-pointers attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.team_agg.fg3_pct",
            "description": ("Team three-point percentage"),
        },
    )
    ftm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.ftm",
            "description": ("Team free throws made"),
        },
    )
    fta: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.fta",
            "description": ("Team free throws attempted"),
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.team_agg.ft_pct",
            "description": ("Team free throw percentage"),
        },
    )
    oreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.oreb",
            "description": ("Team offensive rebounds"),
        },
    )
    dreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.dreb",
            "description": ("Team defensive rebounds"),
        },
    )
    reb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.reb",
            "description": "Team total rebounds",
        },
    )
    ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.ast",
            "description": "Team assists",
        },
    )
    stl: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.stl",
            "description": "Team steals",
        },
    )
    blk: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.blk",
            "description": "Team blocks",
        },
    )
    tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.tov",
            "description": "Team turnovers",
        },
    )
    pf: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.pf",
            "description": "Team personal fouls",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "derived.team_agg.pts",
            "description": "Team total points",
        },
    )
    pts_qtr1: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR1"),
            "description": ("Team first quarter points"),
        },
    )
    pts_qtr2: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR2"),
            "description": ("Team second quarter points"),
        },
    )
    pts_qtr3: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR3"),
            "description": ("Team third quarter points"),
        },
    )
    pts_qtr4: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS_QTR4"),
            "description": ("Team fourth quarter points"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
