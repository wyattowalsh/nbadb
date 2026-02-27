from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactWinProbabilitySchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.GAME_ID"
            ),
            "description": (
                "Unique game identifier"
            ),
            "fk_ref": "dim_game.game_id",
        },
    )
    event_num: int = pa.Field(
        ge=0,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.EVENT_NUM"
            ),
            "description": (
                "Event sequence number"
            ),
        },
    )
    period: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.PERIOD"
            ),
            "description": (
                "Game period (1-4 qtrs, 5+ OT)"
            ),
        },
    )
    pc_time_string: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP"
                ".PCTIMESTRING"
            ),
            "description": (
                "Period clock time string"
            ),
        },
    )
    home_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_PCT"
            ),
            "description": (
                "Home team win probability"
            ),
        },
    )
    visitor_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.VISITOR_PCT"
            ),
            "description": (
                "Visitor team win probability"
            ),
        },
    )
    home_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_PTS"
            ),
            "description": (
                "Home team points at event"
            ),
        },
    )
    visitor_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.VISITOR_PTS"
            ),
            "description": (
                "Visitor team points at event"
            ),
        },
    )
    home_score_margin: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP"
                ".HOME_SCORE_MARGIN"
            ),
            "description": (
                "Home team score margin"
            ),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": (
                "Season year (e.g. 2024-25)"
            ),
        },
    )
