from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameAdvancedSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PLAYER_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.MIN",
            "description": "Parsed player minutes",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_year",
            "description": "Season identifier from the game dimension",
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OFF_RATING"),
            "description": "Offensive rating",
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DEF_RATING"),
            "description": "Defensive rating",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.NET_RATING"),
            "description": "Net rating",
        },
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_PCT"),
            "description": "Assist percentage",
        },
    )
    ast_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_TOV"),
            "description": ("Assist-to-turnover ratio"),
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_RATIO"),
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OREB_PCT"),
            "description": ("Offensive rebound percentage"),
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DREB_PCT"),
            "description": ("Defensive rebound percentage"),
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.REB_PCT"),
            "description": ("Total rebound percentage"),
        },
    )
    tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.TOV_PCT",
            "description": "Turnover percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.EFG_PCT"),
            "description": ("Effective field goal percentage"),
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TS_PCT"),
            "description": ("True shooting percentage"),
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.USG_PCT"),
            "description": "Usage percentage",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PACE"),
            "description": "Pace factor",
        },
    )
    pace_per40: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.PACE_PER40",
            "description": "Provider pace normalized to 40 minutes",
        },
    )
    poss: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.POSS"),
            "description": "Possessions",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PIE"),
            "description": ("Player impact estimate"),
        },
    )
    fta_rate: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.FTA_RATE"),
            "description": ("Free throw attempt rate"),
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.E_OFF_RATING",
            "description": "Provider estimated offensive rating",
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.E_DEF_RATING",
            "description": "Provider estimated defensive rating",
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.E_NET_RATING",
            "description": "Provider estimated net rating",
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.E_USG_PCT",
            "description": "Provider estimated usage percentage",
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreAdvancedV3.PlayerStats.E_PACE",
            "description": "Provider estimated pace",
        },
    )
