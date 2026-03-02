from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactGameScoringSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("Scoreboard.LineScore.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("Scoreboard.LineScore.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    side: str = pa.Field(
        isin=["home", "away"],
        metadata={
            "source": "derived.side",
            "description": ("Home or away designation"),
        },
    )
    period: int = pa.Field(
        gt=0,
        metadata={
            "source": "derived.period",
            "description": ("Period number (1-4 qtrs, 5+ OT)"),
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("Scoreboard.LineScore.PTS"),
            "description": ("Points scored in period"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
