from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


class AggOnOffSplitsSchema(BaseSchema):
    entity_type: str = pa.Field(
        isin=["player", "team", "player_detail"],
        metadata={"description": "Curated player split, provider detail, or team overall"},
    )
    source_kind: str = pa.Field(
        isin=[
            "reconciled_summary_detail",
            "provider_detail",
            "provider_detail_overall",
        ],
        metadata={"description": "Provider authority used for the row"},
    )
    entity_id: int = pa.Field(
        gt=0, metadata={"description": "Player identifier or team identifier"}
    )
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Request season (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Request season type"})
    on_off: str = pa.Field(
        isin=["On", "Off", "Overall"],
        metadata={"description": "Provider court-status split"},
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games covered"})
    min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Provider minutes in this split"}
    )
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Recomputed FGM / FGA"},
    )
    provider_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Recomputed FG3M / FG3A"},
    )
    provider_fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Recomputed FTM / FTA"},
    )
    provider_ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
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
    off_rating: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Provider offensive rating for this split"},
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Provider defensive rating for this split"},
    )
    net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Provider net rating for this split"}
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Derived true-shooting percentage from provider totals"},
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Derived effective field-goal percentage"},
    )
    pts_per48: float | None = pa.Field(nullable=True, ge=0.0)
    reb_per48: float | None = pa.Field(nullable=True, ge=0.0)
    ast_per48: float | None = pa.Field(nullable=True, ge=0.0)
    on_off_pair_complete: bool | None = pa.Field(
        nullable=True,
        metadata={"description": "Both On and Off rows exist at the exact player grain"},
    )
    on_gp: int | None = pa.Field(nullable=True, ge=0)
    off_gp: int | None = pa.Field(nullable=True, ge=0)
    on_min: float | None = pa.Field(nullable=True, ge=0.0)
    off_min: float | None = pa.Field(nullable=True, ge=0.0)
    off_rating_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "On-court minus off-court offensive rating"},
    )
    def_rating_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "On-court minus off-court defensive rating"},
    )
    net_rating_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "On-court minus off-court net rating"},
    )
    plus_minus_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "On-court minus off-court provider plus-minus"},
    )


derived_output_schema(literal_fields={"entity_type", "source_kind", "on_off"})(AggOnOffSplitsSchema)
