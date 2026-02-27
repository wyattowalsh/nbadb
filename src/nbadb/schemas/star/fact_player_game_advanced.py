from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameAdvancedSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": (
                "Unique game identifier"
            ),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PLAYER_ID"
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
                "BoxScoreAdvancedV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.OFF_RATING"
            ),
            "description": "Offensive rating",
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.DEF_RATING"
            ),
            "description": "Defensive rating",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.NET_RATING"
            ),
            "description": "Net rating",
        },
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_PCT"
            ),
            "description": "Assist percentage",
        },
    )
    ast_to: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_TOV"
            ),
            "description": (
                "Assist-to-turnover ratio"
            ),
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_RATIO"
            ),
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.OREB_PCT"
            ),
            "description": (
                "Offensive rebound percentage"
            ),
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.DREB_PCT"
            ),
            "description": (
                "Defensive rebound percentage"
            ),
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.REB_PCT"
            ),
            "description": (
                "Total rebound percentage"
            ),
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.EFG_PCT"
            ),
            "description": (
                "Effective field goal percentage"
            ),
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TS_PCT"
            ),
            "description": (
                "True shooting percentage"
            ),
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.USG_PCT"
            ),
            "description": "Usage percentage",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PACE"
            ),
            "description": "Pace factor",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PIE"
            ),
            "description": (
                "Player impact estimate"
            ),
        },
    )
    poss: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.POSS"
            ),
            "description": "Possessions",
        },
    )
    fta_rate: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.FTA_RATE"
            ),
            "description": (
                "Free throw attempt rate"
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
