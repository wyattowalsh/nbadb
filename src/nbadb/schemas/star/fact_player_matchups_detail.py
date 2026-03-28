from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerMatchupsDetailSchema(BaseSchema):
    detail_source: str = pa.Field(
        isin=["player_compare", "player_vs_player"],
        metadata={
            "source": "derived.player_matchups_detail.detail_source",
            "description": "Comparison endpoint family that produced the row",
        },
    )
    detail_variant: str = pa.Field(
        isin=["individual", "overall_compare", "on_off_court", "overall"],
        metadata={
            "source": "derived.player_matchups_detail.detail_variant",
            "description": "Result-set variant within the comparison family",
        },
    )
    group_set: str = pa.Field(metadata={"description": "Matchup grouping set"})
    group_value: str | None = pa.Field(
        nullable=True, metadata={"description": "Matchup grouping value"}
    )
    description: str | None = pa.Field(
        nullable=True, metadata={"description": "Matchup description"}
    )
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)
