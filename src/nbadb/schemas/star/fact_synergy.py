from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactSynergySchema(BaseSchema):
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.PLAYER_ID"
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
                "SynergyPlayTypes"
                ".SynergyPlayType.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    play_type: str = pa.Field(
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.PLAY_TYPE"
            ),
            "description": (
                "Play type (Isolation, PnR, etc.)"
            ),
        },
    )
    type_grouping: str = pa.Field(
        isin=["offensive", "defensive"],
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType"
                ".TYPE_GROUPING"
            ),
            "description": (
                "Offensive or defensive grouping"
            ),
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.GP"
            ),
            "description": "Games played",
        },
    )
    poss_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.POSS_PCT"
            ),
            "description": (
                "Possession percentage"
            ),
        },
    )
    poss: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.POSS"
            ),
            "description": "Possessions",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.PTS"
            ),
            "description": "Points scored",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.FGA"
            ),
            "description": (
                "Field goals attempted"
            ),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.FG_PCT"
            ),
            "description": (
                "Field goal percentage"
            ),
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.EFG_PCT"
            ),
            "description": (
                "Effective FG percentage"
            ),
        },
    )
    ppp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.PPP"
            ),
            "description": (
                "Points per possession"
            ),
        },
    )
    score_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.SCORE_PCT"
            ),
            "description": (
                "Scoring frequency percentage"
            ),
        },
    )
    tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.TOV_PCT"
            ),
            "description": (
                "Turnover percentage"
            ),
        },
    )
    ft_poss_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.FT_POSS_PCT"
            ),
            "description": (
                "Free throw possession pct"
            ),
        },
    )
    percentile: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "SynergyPlayTypes"
                ".SynergyPlayType.PERCENTILE"
            ),
            "description": (
                "League percentile ranking"
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
