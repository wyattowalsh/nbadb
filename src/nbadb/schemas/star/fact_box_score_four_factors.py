from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactBoxScoreFourFactorsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "description": "Unique game identifier",
            "fk_ref": "dim_game.game_id",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "description": "Unique player identifier",
            "fk_ref": "dim_player.player_id",
        },
    )
    effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Effective field goal percentage",
        },
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "description": "Free throw attempt rate",
        },
    )
    team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Team turnover percentage",
        },
    )
    offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Offensive rebound percentage",
        },
    )
    opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Opponent effective field goal percentage",
        },
    )
    opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "description": "Opponent free throw attempt rate",
        },
    )
    opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Opponent team turnover percentage",
        },
    )
    opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "description": "Opponent offensive rebound percentage",
        },
    )
