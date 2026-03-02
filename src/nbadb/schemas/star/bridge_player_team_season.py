from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgePlayerTeamSeasonSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.PERSON_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    jersey_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.JERSEY"),
            "description": ("Jersey number for season"),
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.CommonPlayerInfo.POSITION"),
            "description": ("Position played for season"),
        },
    )
