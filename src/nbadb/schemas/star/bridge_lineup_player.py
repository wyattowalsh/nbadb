from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgeLineupPlayerSchema(BaseSchema):
    group_id: str = pa.Field(
        metadata={
            "source": ("LeagueDashLineups.Lineups.GROUP_ID"),
            "description": ("Lineup group identifier"),
            "fk_ref": ("fact_lineup_stats.group_id"),
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "derived.player_id",
            "description": ("Player in lineup"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    position_in_lineup: int | None = pa.Field(
        nullable=True,
        ge=1,
        le=5,
        metadata={
            "source": ("derived.position_in_lineup"),
            "description": ("Position index in lineup (1-5)"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
