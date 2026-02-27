from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimGameSchema(BaseSchema):
    game_id: str = pa.Field(
        unique=True,
        metadata={
            "source": "LeagueGameLog.GAME_ID",
            "description": "Primary key — NBA game identifier",
        },
    )
    game_date: str = pa.Field(
        metadata={
            "source": "LeagueGameLog.GAME_DATE",
            "description": "Date the game was played",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": "Season year (e.g. 2024-25)",
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": "Season type (Regular Season, Playoffs, etc.)",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "derived.home_team_id",
            "description": "Home team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "derived.visitor_team_id",
            "description": "Visitor team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    matchup: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.MATCHUP",
            "description": "Matchup string (e.g. LAL vs. BOS)",
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.arena_name",
            "description": "Arena name",
        },
    )
    arena_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.arena_city",
            "description": "Arena city",
        },
    )
