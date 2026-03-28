from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactShotChartLeagueAveragesSchema(BaseSchema):
    average_source: str = pa.Field(
        isin=["shot_chart_detail", "shot_chart_lineup_detail"],
        metadata={
            "source": "derived.shot_chart_league_averages.average_source",
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
