from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(
    literal_fields={"home_lineup_id", "away_lineup_id", "ambiguity_reason", "algorithm_version"},
)
class FactLineupStintSchema(BaseSchema):
    """Exact-five GameRotation stints with conservative possession responses."""

    game_id: str = pa.Field(metadata={"fk_ref": "dim_game.game_id"})
    stint_number: int = pa.Field(ge=1)
    stint_id: str
    home_team_id: int = pa.Field(gt=0)
    away_team_id: int = pa.Field(gt=0)
    home_lineup_id: str
    away_lineup_id: str
    home_player_ids: str
    away_player_ids: str
    stint_start_elapsed_tenths: float = pa.Field(ge=0)
    stint_end_elapsed_tenths: float = pa.Field(gt=0)
    duration_seconds: float = pa.Field(gt=0)
    source_interval_count: int = pa.Field(eq=10)
    source_possession_count: int = pa.Field(ge=0)
    first_possession_number: int | None = pa.Field(nullable=True, ge=1)
    last_possession_number: int | None = pa.Field(nullable=True, ge=1)
    first_source_action_number: int | None = pa.Field(nullable=True, ge=0)
    last_source_action_number: int | None = pa.Field(nullable=True, ge=0)
    home_possessions: int = pa.Field(ge=0)
    away_possessions: int = pa.Field(ge=0)
    home_points: int | None = pa.Field(nullable=True, ge=0)
    away_points: int | None = pa.Field(nullable=True, ge=0)
    home_net_points: int | None = pa.Field(nullable=True)
    possession_boundary_crossings: int = pa.Field(ge=0)
    unplaced_possession_count: int = pa.Field(ge=0)
    lineup_is_exact: bool = pa.Field(eq=True)
    response_is_complete: bool
    is_ambiguous: bool
    ambiguity_reason: str | None = pa.Field(nullable=True)
    algorithm_version: str = pa.Field(eq="game_rotation_exact_five_v1")


__all__ = ["FactLineupStintSchema"]
