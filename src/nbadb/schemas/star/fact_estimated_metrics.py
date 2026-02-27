from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerEstimatedMetricsSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".PLAYER_ID"
            ),
            "description": (
                "Player identifier"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics.GP"
            ),
            "description": "Games played",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics.W"
            ),
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics.L"
            ),
            "description": "Losses",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics.MIN"
            ),
            "description": "Minutes played",
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_OFF_RATING"
            ),
            "description": (
                "Estimated offensive rating"
            ),
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_DEF_RATING"
            ),
            "description": (
                "Estimated defensive rating"
            ),
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_NET_RATING"
            ),
            "description": (
                "Estimated net rating"
            ),
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_PACE"
            ),
            "description": (
                "Estimated pace"
            ),
        },
    )
    e_ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_AST_RATIO"
            ),
            "description": (
                "Estimated assist ratio"
            ),
        },
    )
    e_oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_OREB_PCT"
            ),
            "description": (
                "Estimated offensive rebound pct"
            ),
        },
    )
    e_dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_DREB_PCT"
            ),
            "description": (
                "Estimated defensive rebound pct"
            ),
        },
    )
    e_reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_REB_PCT"
            ),
            "description": (
                "Estimated total rebound pct"
            ),
        },
    )
    e_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_TOV_PCT"
            ),
            "description": (
                "Estimated turnover percentage"
            ),
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerEstimatedMetrics"
                ".PlayerEstimatedMetrics"
                ".E_USG_PCT"
            ),
            "description": (
                "Estimated usage percentage"
            ),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": (
                "Season year (e.g. 2024-25)"
            ),
        },
    )


# Alias for __init__.py backward compatibility
FactEstimatedMetricsSchema = (
    FactPlayerEstimatedMetricsSchema
)


class FactTeamEstimatedMetricsSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics.GP"
            ),
            "description": "Games played",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics.W"
            ),
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics.L"
            ),
            "description": "Losses",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics.MIN"
            ),
            "description": "Minutes played",
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_OFF_RATING"
            ),
            "description": (
                "Estimated offensive rating"
            ),
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_DEF_RATING"
            ),
            "description": (
                "Estimated defensive rating"
            ),
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_NET_RATING"
            ),
            "description": (
                "Estimated net rating"
            ),
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_PACE"
            ),
            "description": (
                "Estimated pace"
            ),
        },
    )
    e_ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_AST_RATIO"
            ),
            "description": (
                "Estimated assist ratio"
            ),
        },
    )
    e_oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_OREB_PCT"
            ),
            "description": (
                "Estimated offensive rebound pct"
            ),
        },
    )
    e_dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_DREB_PCT"
            ),
            "description": (
                "Estimated defensive rebound pct"
            ),
        },
    )
    e_reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_REB_PCT"
            ),
            "description": (
                "Estimated total rebound pct"
            ),
        },
    )
    e_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamEstimatedMetrics"
                ".TeamEstimatedMetrics"
                ".E_TOV_PCT"
            ),
            "description": (
                "Estimated turnover percentage"
            ),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": (
                "Season year (e.g. 2024-25)"
            ),
        },
    )
