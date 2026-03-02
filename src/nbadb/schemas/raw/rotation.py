from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawGameRotationSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("GameRotation.HomeTeam.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_ID"),
            "description": "Team identifier",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_NAME"),
            "description": "Team name",
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PERSON_ID"),
            "description": "Player person identifier",
        },
    )
    player_first: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_FIRST"),
            "description": "Player first name",
        },
    )
    player_last: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_LAST"),
            "description": "Player last name",
        },
    )
    in_time_real: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.IN_TIME_REAL"),
            "description": ("Real time player entered game"),
        },
    )
    out_time_real: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.OUT_TIME_REAL"),
            "description": ("Real time player exited game"),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_PTS"),
            "description": ("Points scored during stint"),
        },
    )
    pt_diff: float | None = pa.Field(
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
