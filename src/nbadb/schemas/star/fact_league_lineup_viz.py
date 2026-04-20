from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactLeagueLineupVizSchema(BaseSchema):
    group_id: str = pa.Field(
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.GROUP_ID"),
            "description": "Lineup group identifier",
        },
    )
    group_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.GROUP_NAME"),
            "description": "Lineup player names",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.MIN"),
            "description": "Minutes played",
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OFF_RATING"),
            "description": "Offensive rating",
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.DEF_RATING"),
            "description": "Defensive rating",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.NET_RATING"),
            "description": "Net rating",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PACE"),
            "description": "Pace factor",
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TS_PCT"),
            "description": "True shooting percentage",
        },
    )
    fta_rate: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.FTA_RATE"),
            "description": "Free throw attempt rate",
        },
    )
    tm_ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TM_AST_PCT"),
            "description": "Team assist percentage",
        },
    )
    pct_fga_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_FGA_2PT"),
            "description": ("Percentage of field goal attempts from two-point range"),
        },
    )
    pct_fga_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_FGA_3PT"),
            "description": ("Percentage of field goal attempts from three-point range"),
        },
    )
    pct_pts_2pt_mr: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_2PT_MR"),
            "description": ("Percentage of points from mid-range two-pointers"),
        },
    )
    pct_pts_fb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_FB"),
            "description": ("Percentage of points from fast breaks"),
        },
    )
    pct_pts_ft: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_FT"),
            "description": ("Percentage of points from free throws"),
        },
    )
    pct_pts_paint: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_PAINT"),
            "description": ("Percentage of points in the paint"),
        },
    )
    pct_ast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_AST_FGM"),
            "description": ("Percentage of assisted field goals"),
        },
    )
    pct_uast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_UAST_FGM"),
            "description": ("Percentage of unassisted field goals"),
        },
    )
    opp_fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_FG3_PCT"),
            "description": ("Opponent three-point percentage"),
        },
    )
    opp_efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_EFG_PCT"),
            "description": ("Opponent effective field goal percentage"),
        },
    )
    opp_fta_rate: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_FTA_RATE"),
            "description": ("Opponent free throw attempt rate"),
        },
    )
    opp_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_TOV_PCT"),
            "description": ("Opponent turnover percentage"),
        },
    )
