from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class AggOnOffSplitsSchema(BaseSchema):
    entity_type: str = pa.Field(isin=["player", "team", "player_detail"])
    entity_id: int | None = pa.Field(nullable=True, gt=0)
    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    on_off: str = pa.Field()
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    off_rating: float | None = pa.Field(nullable=True, ge=0.0)
    def_rating: float | None = pa.Field(nullable=True, ge=0.0)
    net_rating: float | None = pa.Field(nullable=True)
