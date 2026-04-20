from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


class FactTeamAvailableSeasonsSchema(BaseSchema):
    season_id: str = pa.Field(nullable=False)


class FactOnOffDetailSchema(BaseSchema):
    court_status: str = pa.Field(
        nullable=False,
        isin=[
            "detail_overall",
            "detail_off_court",
            "detail_on_court",
            "summary_overall",
            "summary_off_court",
            "summary_on_court",
        ],
    )
    group_set: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    group_value: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    off_rating: float | None = pa.Field(nullable=True)
    def_rating: float | None = pa.Field(nullable=True)
    net_rating: float | None = pa.Field(nullable=True)


class FactTeamHistoricalSchema(BaseSchema):
    history_type: str = pa.Field(
        nullable=False,
        isin=["leaders", "year_by_year", "year_by_year_stats"],
    )
    team_id: int = pa.Field(gt=0, nullable=False)


class FactTeamHistoryDetailSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    city: str | None = pa.Field(nullable=True)
    nickname: str | None = pa.Field(nullable=True)
    yearfounded: int | None = pa.Field(nullable=True, gt=1900)
    yearactivetill: int | None = pa.Field(nullable=True, gt=1900)


derived_output_schema()(FactTeamAvailableSeasonsSchema)
derived_output_schema(literal_fields={"court_status"})(FactOnOffDetailSchema)
derived_output_schema(literal_fields={"history_type"})(FactTeamHistoricalSchema)
derived_output_schema()(FactTeamHistoryDetailSchema)
