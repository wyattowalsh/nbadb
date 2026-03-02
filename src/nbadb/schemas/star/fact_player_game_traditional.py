from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameTraditionalSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLAYER_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.MIN"),
            "description": "Minutes played",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PTS"),
            "description": "Points scored",
        },
    )
    reb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.AST"),
            "description": "Assists",
        },
    )
    stl: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.STL"),
            "description": "Steals",
        },
    )
    blk: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.BLK"),
            "description": "Blocks",
        },
    )
    tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TOV"),
            "description": "Turnovers",
        },
    )
    pf: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PF"),
            "description": "Personal fouls",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGA"),
            "description": ("Field goals attempted"),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG_PCT"),
            "description": ("Field goal percentage"),
        },
    )
    fg3m: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3A"),
            "description": ("Three-pointers attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3_PCT"),
            "description": ("Three-point percentage"),
        },
    )
    ftm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTA"),
            "description": ("Free throws attempted"),
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FT_PCT"),
            "description": ("Free throw percentage"),
        },
    )
    oreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.OREB"),
            "description": ("Offensive rebounds"),
        },
    )
    dreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.DREB"),
            "description": ("Defensive rebounds"),
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLUS_MINUS"),
            "description": "Plus-minus",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.START_POSITION"),
            "description": ("Starting position (F, C, G)"),
        },
    )
