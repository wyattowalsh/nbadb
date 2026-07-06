from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawDunkScoreLeadersSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "DunkScoreLeaders.dunks.playerId",
            "description": "NBA player identifier from the dunk score leaderboard payload.",
            "fk_ref": "dim_player.player_id",
        },
    )
    dunk_score: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "DunkScoreLeaders.dunks.dunkScore",
            "description": "Endpoint-provided dunk score leaderboard value.",
        },
    )


class RawGravityLeadersSchema(BaseSchema):
    playerid: int = pa.Field(
        gt=0,
        metadata={
            "source": "GravityLeaders.leaders.PLAYERID",
            "description": "NBA player identifier from the gravity leaderboard payload.",
            "fk_ref": "dim_player.player_id",
        },
    )
    gravityscore: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "GravityLeaders.leaders.GRAVITYSCORE",
            "description": "Endpoint-provided player gravity score leaderboard value.",
        },
    )
