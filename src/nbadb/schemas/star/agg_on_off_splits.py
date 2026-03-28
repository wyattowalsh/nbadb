from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class AggOnOffSplitsSchema(BaseSchema):
    entity_type: str = pa.Field(
        isin=["player", "team", "player_detail"],
        metadata={"description": "Entity type (player, team, or player_detail)"},
    )
    entity_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Entity identifier (player_id or team_id)"}
    )
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    on_off: str = pa.Field(metadata={"description": "On-court or off-court indicator"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes played"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points scored"})
    reb: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Total rebounds"})
    ast: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Assists"})
    off_rating: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Offensive rating"}
    )
    def_rating: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Defensive rating"}
    )
    net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Net rating (offensive - defensive)"}
    )
