from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(
    literal_fields={"team_side", "lineup_algorithm_version", "design_version"},
)
class FactRapmDesignSchema(BaseSchema):
    """Unfitted player indicators and responses for RAPM-like models."""

    design_row_id: str
    game_id: str = pa.Field(metadata={"fk_ref": "dim_game.game_id"})
    stint_id: str
    stint_number: int = pa.Field(ge=1)
    player_id: int = pa.Field(gt=0)
    team_id: int = pa.Field(gt=0)
    team_side: str = pa.Field(isin=["home", "away"])
    design_value: float = pa.Field(isin=[-1.0, 1.0])
    response_home_net_points: int
    exposure_seconds: float = pa.Field(gt=0)
    source_possession_count: int = pa.Field(ge=0)
    first_source_action_number: int = pa.Field(ge=0)
    last_source_action_number: int = pa.Field(ge=0)
    lineup_is_exact: bool = pa.Field(eq=True)
    response_is_complete: bool = pa.Field(eq=True)
    is_ambiguous: bool = pa.Field(eq=False)
    ambiguity_reason: str | None = pa.Field(nullable=True)
    lineup_algorithm_version: str = pa.Field(eq="game_rotation_exact_five_v1")
    design_version: str = pa.Field(eq="rapm_long_form_v1")


__all__ = ["FactRapmDesignSchema"]
