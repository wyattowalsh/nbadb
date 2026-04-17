from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(literal_fields={"average_source"})
class FactShotChartLeagueAveragesSchema(BaseSchema):
    average_source: str = pa.Field(
        isin=["shot_chart_detail", "shot_chart_lineup_detail"],
        metadata={
            "description": "Shot-chart request family that produced the league-average row",
        },
    )
    grid_type: str | None = pa.Field(nullable=True)
    shot_zone_basic: str | None = pa.Field(nullable=True)
    shot_zone_area: str | None = pa.Field(nullable=True)
    shot_zone_range: str | None = pa.Field(nullable=True)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0)
