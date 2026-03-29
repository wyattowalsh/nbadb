from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactWinProbPbpSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.GAME_ID",
            "description": "Unique game identifier",
            "fk_ref": "dim_game.game_id",
        },
    )
    event_num: int = pa.Field(
        ge=0,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.EVENT_NUM",
            "description": "Event sequence number within the game",
        },
    )
    home_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.HOME_PCT",
            "description": "Home team win probability (0.0–1.0)",
        },
    )
    visitor_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.VISITOR_PCT",
            "description": "Visitor team win probability (0.0–1.0)",
        },
    )
    home_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.HOME_PTS",
            "description": "Home team points at event",
        },
    )
    visitor_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.VISITOR_PTS",
            "description": "Visitor team points at event",
        },
    )
    home_score_margin: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.HOME_SCORE_MARGIN",
            "description": "Home team score margin at event",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.PERIOD",
            "description": "Game period (1–4 quarters, 5+ overtime)",
        },
    )
    seconds_remaining: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.SECONDS_REMAINING",
            "description": "Seconds remaining in the period",
        },
    )
    home_poss_ind: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.HOME_POSS_IND",
            "description": "Home team possession indicator (0/1)",
        },
    )
    home_g: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.HOME_G",
            "description": "Home team game count",
        },
    )
    description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.DESCRIPTION",
            "description": "Play-by-play event description",
        },
    )
    location: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.LOCATION",
            "description": "Event location indicator (Home/Away)",
        },
    )
    pctimestring: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.PCTIMESTRING",
            "description": "Period clock time string (e.g. 12:00)",
        },
    )
    isvisible: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "WinProbabilityPBP.WinProbPBP.ISVISIBLE",
            "description": "Whether the event is visible in the play-by-play",
        },
    )
