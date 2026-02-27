from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgePlayPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.GAME_ID"
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
                "PlayByPlayV3"
                ".PlayByPlay.EVENTNUM"
            ),
            "description": (
                "Event sequence number"
            ),
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "derived.player_id",
            "description": (
                "Player involved in play"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "derived.team_id",
            "description": (
                "Player team identifier"
            ),
            "fk_ref": "dim_team.team_id",
        },
    )
    player_role: str = pa.Field(
        isin=[
            "primary",
            "secondary",
            "tertiary",
        ],
        metadata={
            "source": "derived.player_role",
            "description": (
                "Role in play event"
            ),
        },
    )
