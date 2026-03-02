from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactTrackingDefenseSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.CLOSE_DEF_PERSON_ID"),
            "description": ("Defender player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    defense_category: str = pa.Field(
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.DEFENSE_CATEGORY"),
            "description": ("Defense category (Overall, 3pt, etc.)"),
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.GP"),
            "description": "Games played",
        },
    )
    g: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.G"),
            "description": "Games",
        },
    )
    freq: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.FREQ"),
            "description": ("Frequency of defense"),
        },
    )
    d_fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.D_FGM"),
            "description": ("Defended field goals made"),
        },
    )
    d_fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.D_FGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    d_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.D_FG_PCT"),
            "description": ("Defended FG percentage"),
        },
    )
    normal_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.NORMAL_FG_PCT"),
            "description": ("Normal (undefended) FG pct"),
        },
    )
    pct_plusminus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPtDefend.LeagueDashPtDefend.PCT_PLUSMINUS"),
            "description": ("FG pct differential (defended vs normal)"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
