from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgeGameTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.TEAM_ID"),
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
    wl: str | None = pa.Field(
        nullable=True,
        isin=["W", "L"],
        metadata={
            "source": ("LeagueGameLog.LeagueGameLog.WL"),
            "description": ("Win or loss result"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
