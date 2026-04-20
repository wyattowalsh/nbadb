from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


class FactDraftBoardSchema(BaseSchema):
    person_id: int = pa.Field(gt=0)
    player_name: str | None = pa.Field(nullable=True)
    season: int | None = pa.Field(nullable=True, ge=1946)
    round_number: int | None = pa.Field(nullable=True, ge=1)
    round_pick: int | None = pa.Field(nullable=True, ge=1)
    overall_pick: int | None = pa.Field(nullable=True, ge=1)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_city: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    team_abbreviation: str | None = pa.Field(nullable=True)
    organization: str | None = pa.Field(nullable=True)
    organization_type: str | None = pa.Field(nullable=True)
    height: str | None = pa.Field(nullable=True)
    weight: str | None = pa.Field(nullable=True)
    position: str | None = pa.Field(nullable=True)
    jersey_number: str | None = pa.Field(nullable=True)
    birthdate: str | None = pa.Field(nullable=True)
    age: float | None = pa.Field(nullable=True, ge=0.0)


derived_output_schema()(FactDraftBoardSchema)
