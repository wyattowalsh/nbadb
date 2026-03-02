from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawSynergyPlayTypesSchema(BaseSchema):
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SEASON_ID"),
            "description": "NBA season identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_ID"),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_NAME"),
            "description": "Team name",
        },
    )
    player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAYER_ID"),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    play_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAY_TYPE"),
            "description": ("Synergy play type classification"),
        },
    )
    type_grouping: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TYPE_GROUPING"),
            "description": ("Offensive or defensive grouping"),
        },
    )
    percentile: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PERCENTILE"),
            "description": ("Percentile rank for play type"),
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.GP"),
            "description": "Games played",
        },
    )
    poss_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.POSS_PCT"),
            "description": ("Percentage of possessions"),
        },
    )
    ppp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PPP"),
            "description": "Points per possession",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    ft_pct_adjust: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FT_PCT_ADJUST"),
            "description": ("Free throw percentage adjusted"),
        },
    )
    to_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TO_PCT"),
            "description": "Turnover percentage",
        },
    )
    sf_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SF_PCT"),
            "description": "Shooting foul percentage",
        },
    )
    plusone_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLUSONE_PCT"),
            "description": ("And-one conversion percentage"),
        },
    )
    score_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SCORE_PCT"),
            "description": "Scoring percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.EFG_PCT"),
            "description": ("Effective field goal percentage"),
        },
    )
    poss: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.POSS"),
            "description": "Total possessions",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PTS"),
            "description": "Total points scored",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGM"),
            "description": "Field goals made",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGA"),
            "description": "Field goals attempted",
        },
    )
    fgmx: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGMX"),
            "description": "Field goals missed",
        },
    )
