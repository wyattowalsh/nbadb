from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactGameLeadersSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".gameId"
            ),
            "description": "Unique game identifier",
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".teamId"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    leader_type: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".leaderType"
            ),
            "description": (
                "Leader category (home or away)"
            ),
        },
    )
    person_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".personId"
            ),
            "description": "Unique player identifier",
            "fk_ref": "dim_player.player_id",
        },
    )
    name: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".name"
            ),
            "description": "Player display name",
        },
    )
    player_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".playerSlug"
            ),
            "description": "Player URL slug",
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".jerseyNum"
            ),
            "description": "Player jersey number",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".position"
            ),
            "description": "Player position",
        },
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".teamTricode"
            ),
            "description": "Three-letter team code",
        },
    )
    points: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".points"
            ),
            "description": "Points scored",
        },
    )
    rebounds: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".rebounds"
            ),
            "description": "Total rebounds",
        },
    )
    assists: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "ScoreboardV3.GameLeaders"
                ".assists"
            ),
            "description": "Total assists",
        },
    )
