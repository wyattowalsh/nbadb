from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameTrackingSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PLAYER_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    spd: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.SPD"),
            "description": ("Average speed (mph)"),
        },
    )
    dist: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DIST"),
            "description": ("Distance traveled (miles)"),
        },
    )
    orbc: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.ORBC"),
            "description": ("Offensive rebound chances"),
        },
    )
    drbc: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DRBC"),
            "description": ("Defensive rebound chances"),
        },
    )
    rbc: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.RBC"),
            "description": ("Total rebound chances"),
        },
    )
    tchs: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TCHS"),
            "description": "Touches",
        },
    )
    front_ct_tchs: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.FRONT_CT_TOUCHES"),
            "description": ("Front court touches"),
        },
    )
    time_of_poss: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TIME_OF_POSS"),
            "description": ("Time of possession (min)"),
        },
    )
    passes: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PASSES"),
            "description": "Passes made",
        },
    )
    ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.AST"),
            "description": "Assists",
        },
    )
    ft_ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.FTAST"),
            "description": ("Free throw assists"),
        },
    )
    cfgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGM"),
            "description": ("Contested field goals made"),
        },
    )
    cfga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGA"),
            "description": ("Contested field goals attempted"),
        },
    )
    cfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFG_PCT"),
            "description": ("Contested FG percentage"),
        },
    )
    ufgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGM"),
            "description": ("Uncontested FG made"),
        },
    )
    ufga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGA"),
            "description": ("Uncontested FG attempted"),
        },
    )
    ufg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFG_PCT"),
            "description": ("Uncontested FG percentage"),
        },
    )
    dfgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGM"),
            "description": ("Defended field goals made"),
        },
    )
    dfga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    dfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFG_PCT"),
            "description": ("Defended FG percentage"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
