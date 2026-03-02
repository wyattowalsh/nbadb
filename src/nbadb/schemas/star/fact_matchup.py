from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactMatchupSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.OFF_PLAYER_ID"),
            "description": ("Offensive player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.OFF_TEAM_ID"),
            "description": ("Offensive team identifier"),
            "fk_ref": "dim_team.team_id",
        },
    )
    def_player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.DEF_PLAYER_ID"),
            "description": ("Defensive player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    def_team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.DEF_TEAM_ID"),
            "description": ("Defensive team identifier"),
            "fk_ref": "dim_team.team_id",
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.PARTIAL_POSS"),
            "description": ("Matchup minutes"),
        },
    )
    poss: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.POSS"),
            "description": "Possessions",
        },
    )
    player_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.PLAYER_PTS"),
            "description": ("Points scored by offensive player"),
        },
    )
    team_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.TEAM_PTS"),
            "description": ("Team points during matchup"),
        },
    )
    matchup_ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_AST"),
            "description": ("Assists during matchup"),
        },
    )
    matchup_tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_TOV"),
            "description": ("Turnovers during matchup"),
        },
    )
    matchup_blk: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_BLK"),
            "description": ("Blocks during matchup"),
        },
    )
    matchup_fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_FGM"),
            "description": ("Field goals made during matchup"),
        },
    )
    matchup_fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_FGA"),
            "description": ("Field goals attempted in matchup"),
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerMatchups.MATCHUP_FG_PCT"),
            "description": ("FG percentage during matchup"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
