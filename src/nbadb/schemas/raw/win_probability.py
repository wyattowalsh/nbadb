from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawWinProbabilitySchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    event_num: int = pa.Field(
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.EVENT_NUM"
            ),
            "description": "Event sequence number",
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
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_PTS"
            ),
            "description": "Home team points",
        },
    )
    visitor_pts: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.VISITOR_PTS"
            ),
            "description": "Visitor team points",
        },
    )
    home_score_margin: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_SCORE_MARGIN"
            ),
            "description": (
                "Home team score margin"
            ),
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.PERIOD"
            ),
            "description": "Game period number",
        },
    )
    seconds_remaining: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.SECONDS_REMAINING"
            ),
            "description": (
                "Seconds remaining in period"
            ),
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_TEAM_ID"
            ),
            "description": (
                "Home team identifier"
            ),
        },
    )
    home_team_abb: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.HOME_TEAM_ABB"
            ),
            "description": (
                "Home team abbreviation code"
            ),
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.VISITOR_TEAM_ID"
            ),
            "description": (
                "Visitor team identifier"
            ),
        },
    )
    visitor_team_abb: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.VISITOR_TEAM_ABB"
            ),
            "description": (
                "Visitor team abbreviation code"
            ),
        },
    )
    description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.DESCRIPTION"
            ),
            "description": (
                "Text description of the play"
            ),
        },
    )
    location: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.LOCATION"
            ),
            "description": (
                "Home or away location indicator"
            ),
        },
    )
    pctimestring: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.PCTIMESTRING"
            ),
            "description": (
                "Period clock time string"
            ),
        },
    )
    is_score_change: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "WinProbabilityPBP"
                ".WinProbPBP.IS_SCORE_CHANGE"
            ),
            "description": (
                "Flag indicating if score changed"
            ),
        },
    )
