from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactRotationSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("GameRotation.HomeTeam.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("GameRotation.HomeTeam.PERSON_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    in_time_real: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("GameRotation.HomeTeam.IN_TIME_REAL"),
            "description": ("Check-in time (tenths of sec)"),
        },
    )
    out_time_real: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("GameRotation.HomeTeam.OUT_TIME_REAL"),
            "description": ("Check-out time (tenths of sec)"),
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("GameRotation.HomeTeam.PTS"),
            "description": ("Points during stint"),
        },
    )
    pts_diff: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PT_DIFF"),
            "description": ("Point differential during stint"),
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.USG_PCT"),
            "description": ("Usage percentage during stint"),
        },
    )
    side: str = pa.Field(
        isin=["home", "away"],
        metadata={
            "source": "derived.side",
            "description": ("Home or away designation"),
        },
    )
