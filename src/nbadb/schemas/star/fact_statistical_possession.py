from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(
    literal_fields={"closure_reason", "ambiguity_reason", "algorithm_version"},
)
class FactStatisticalPossessionSchema(BaseSchema):
    """Conservative, versioned statistical possessions from V3 play-by-play."""

    game_id: str = pa.Field(metadata={"fk_ref": "dim_game.game_id"})
    possession_number: int = pa.Field(ge=1)
    period: int = pa.Field(ge=1, le=10)
    offense_team_id: int | None = pa.Field(nullable=True, gt=0)
    defense_team_id: int | None = pa.Field(nullable=True, gt=0)
    home_team_id: int | None = pa.Field(nullable=True, gt=0)
    away_team_id: int | None = pa.Field(nullable=True, gt=0)
    start_action_number: int = pa.Field(ge=0)
    end_action_number: int = pa.Field(ge=0)
    start_clock: str | None = pa.Field(nullable=True)
    end_clock: str | None = pa.Field(nullable=True)
    start_elapsed_tenths: int | None = pa.Field(nullable=True, ge=0)
    end_elapsed_tenths: int | None = pa.Field(nullable=True, ge=0)
    event_count: int = pa.Field(ge=1)
    field_goal_attempts: int = pa.Field(ge=0)
    free_throw_attempts: int = pa.Field(ge=0)
    non_possession_free_throw_attempts: int = pa.Field(ge=0)
    non_possession_free_throw_points: int = pa.Field(ge=0)
    turnovers: int = pa.Field(ge=0)
    offensive_rebounds: int = pa.Field(ge=0)
    points: int | None = pa.Field(nullable=True, ge=0)
    derived_event_points: int | None = pa.Field(nullable=True, ge=0)
    scoreboard_points: int | None = pa.Field(nullable=True, ge=0)
    points_reconciled: bool | None = pa.Field(nullable=True)
    score_before_home: int | None = pa.Field(nullable=True, ge=0)
    score_before_away: int | None = pa.Field(nullable=True, ge=0)
    score_after_home: int | None = pa.Field(nullable=True, ge=0)
    score_after_away: int | None = pa.Field(nullable=True, ge=0)
    statistical_possession_count: int = pa.Field(eq=1)
    legal_control_boundary_count: int = pa.Field(ge=0)
    closure_reason: str = pa.Field(
        isin=[
            "defensive_rebound",
            "defensive_or_team_rebound",
            "end_of_available_events",
            "made_field_goal",
            "made_final_free_throw",
            "period_end",
            "period_transition",
            "possession_loss_violation",
            "turnover",
        ]
    )
    is_complete: bool
    is_ambiguous: bool
    ambiguity_reason: str | None = pa.Field(nullable=True)
    algorithm_version: str = pa.Field(eq="nba_stats_possession_v1")
    derived_team_game_points: int | None = pa.Field(nullable=True, ge=0)
    official_team_game_points: int | None = pa.Field(nullable=True, ge=0)
    team_game_points_reconciled: bool | None = pa.Field(nullable=True)
    derived_complete_team_possessions: int | None = pa.Field(nullable=True, ge=0)
    official_team_possessions: float | None = pa.Field(nullable=True, ge=0)
    team_possessions_reconciled: bool | None = pa.Field(nullable=True)


__all__ = ["FactStatisticalPossessionSchema"]
