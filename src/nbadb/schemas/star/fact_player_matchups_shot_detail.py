from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerMatchupsShotDetailSchema(BaseSchema):
    split_family: str = pa.Field(
        isin=["shot_area", "shot_distance"],
        metadata={
            "source": "derived.player_matchups_shot_detail.split_family",
            "description": "Shot split family for the matchup row",
        },
    )
    split_scope: str = pa.Field(
        isin=["off_court", "on_court", "overall"],
        metadata={
            "source": "derived.player_matchups_shot_detail.split_scope",
            "description": "On/off/overall scope of the shot split",
        },
    )
    group_set: str = pa.Field()
    group_value: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)
