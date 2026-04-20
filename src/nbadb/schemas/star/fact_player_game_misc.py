from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameMiscSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.PLAYER_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    pts_off_tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.PTS_OFF_TOV"),
            "description": ("Points off turnovers"),
        },
    )
    second_chance_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.SECOND_CHANCE_PTS"),
            "description": ("Second chance points"),
        },
    )
    fbps: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.FBPS"),
            "description": "Fast break points",
        },
    )
    pitp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.PITP"),
            "description": ("Points in the paint"),
        },
    )
    opp_pts_off_tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.OPP_PTS_OFF_TOV"),
            "description": ("Opponent points off turnovers"),
        },
    )
    opp_second_chance_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.OPP_SECOND_CHANCE_PTS"),
            "description": ("Opponent second chance points"),
        },
    )
    opp_fbps: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.OPP_FBPS"),
            "description": ("Opponent fast break points"),
        },
    )
    opp_pitp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMiscV3.PlayerStats.OPP_PITP"),
            "description": ("Opponent points in the paint"),
        },
    )
    pct_fga_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_FGA_2PT"),
            "description": ("Percentage of FGA that are 2pt"),
        },
    )
    pct_fga_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_FGA_3PT"),
            "description": ("Percentage of FGA that are 3pt"),
        },
    )
    pct_pts_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_2PT"),
            "description": ("Percentage of points from 2pt"),
        },
    )
    pct_pts_2pt_mr: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_2PT_MR"),
            "description": ("Pct of pts from 2pt mid-range"),
        },
    )
    pct_pts_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_3PT"),
            "description": ("Percentage of points from 3pt"),
        },
    )
    pct_pts_fb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_FB"),
            "description": ("Pct of points from fast breaks"),
        },
    )
    pct_pts_ft: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_FT"),
            "description": ("Pct of points from free throws"),
        },
    )
    pct_pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_OFF_TOV"),
            "description": ("Pct of pts off turnovers"),
        },
    )
    pct_pts_pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_PTS_PITP"),
            "description": ("Pct of pts in the paint"),
        },
    )
    pct_ast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_AST_2PM"),
            "description": ("Pct of 2pt made that are assisted"),
        },
    )
    pct_uast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_UAST_2PM"),
            "description": ("Pct of 2pt made unassisted"),
        },
    )
    pct_ast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_AST_3PM"),
            "description": ("Pct of 3pt made that are assisted"),
        },
    )
    pct_uast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreScoringV3.PlayerStats.PCT_UAST_3PM"),
            "description": ("Pct of 3pt made unassisted"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
