from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawBoxScoreMatchupsSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    off_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.OFF_TEAM_ID"
            ),
            "description": (
                "Offensive team identifier"
            ),
        },
    )
    off_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats"
                ".OFF_TEAM_ABBREVIATION"
            ),
            "description": (
                "Offensive team abbreviation"
            ),
        },
    )
    def_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.DEF_TEAM_ID"
            ),
            "description": (
                "Defensive team identifier"
            ),
        },
    )
    def_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats"
                ".DEF_TEAM_ABBREVIATION"
            ),
            "description": (
                "Defensive team abbreviation"
            ),
        },
    )
    off_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.OFF_PLAYER_ID"
            ),
            "description": (
                "Offensive player identifier"
            ),
        },
    )
    off_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats"
                ".OFF_PLAYER_NAME"
            ),
            "description": "Offensive player name",
        },
    )
    def_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.DEF_PLAYER_ID"
            ),
            "description": (
                "Defensive player identifier"
            ),
        },
    )
    def_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats"
                ".DEF_PLAYER_NAME"
            ),
            "description": "Defensive player name",
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_MIN"
            ),
            "description": (
                "Minutes in matchup"
            ),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.PARTIAL_POSS"
            ),
            "description": (
                "Partial possessions in matchup"
            ),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.PLAYER_PTS"
            ),
            "description": (
                "Player points in matchup"
            ),
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.TEAM_PTS"
            ),
            "description": (
                "Team points in matchup"
            ),
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_AST"
            ),
            "description": "Assists in matchup",
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_TOV"
            ),
            "description": "Turnovers in matchup",
        },
    )
    matchup_blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_BLK"
            ),
            "description": "Blocks in matchup",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FGM"
            ),
            "description": (
                "Field goals made in matchup"
            ),
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FGA"
            ),
            "description": (
                "Field goals attempted in matchup"
            ),
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FG_PCT"
            ),
            "description": (
                "Field goal pct in matchup"
            ),
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FG3M"
            ),
            "description": (
                "Three-pointers made in matchup"
            ),
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FG3A"
            ),
            "description": (
                "Three-pointers attempted"
            ),
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats"
                ".MATCHUP_FG3_PCT"
            ),
            "description": (
                "Three-point pct in matchup"
            ),
        },
    )
    help_blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.HELP_BLK"
            ),
            "description": "Help blocks in matchup",
        },
    )
    help_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.HELP_FGM"
            ),
            "description": (
                "Help field goals made"
            ),
        },
    )
    help_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.HELP_FGA"
            ),
            "description": (
                "Help field goals attempted"
            ),
        },
    )
    help_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.HELP_FG_PCT"
            ),
            "description": (
                "Help field goal percentage"
            ),
        },
    )
    matchup_ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FTM"
            ),
            "description": (
                "Free throws made in matchup"
            ),
        },
    )
    matchup_fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.MATCHUP_FTA"
            ),
            "description": (
                "Free throws attempted"
            ),
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMatchupsV3"
                ".PlayerStats.SWITCHES_ON"
            ),
            "description": (
                "Number of switches onto player"
            ),
        },
    )


class RawLeagueSeasonMatchupsSchema(BaseSchema):
    off_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".OFF_PLAYER_ID"
            ),
            "description": (
                "Offensive player identifier"
            ),
        },
    )
    off_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".OFF_PLAYER_NAME"
            ),
            "description": "Offensive player name",
        },
    )
    def_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".DEF_PLAYER_ID"
            ),
            "description": (
                "Defensive player identifier"
            ),
        },
    )
    def_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".DEF_PLAYER_NAME"
            ),
            "description": "Defensive player name",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.GP"
            ),
            "description": "Games played",
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_MIN"
            ),
            "description": (
                "Minutes in matchup"
            ),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".PARTIAL_POSS"
            ),
            "description": (
                "Partial possessions in matchup"
            ),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.PLAYER_PTS"
            ),
            "description": (
                "Player points in matchup"
            ),
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.TEAM_PTS"
            ),
            "description": (
                "Team points in matchup"
            ),
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_AST"
            ),
            "description": "Assists in matchup",
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_TOV"
            ),
            "description": "Turnovers in matchup",
        },
    )
    matchup_blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_BLK"
            ),
            "description": "Blocks in matchup",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_FGM"
            ),
            "description": (
                "Field goals made in matchup"
            ),
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_FGA"
            ),
            "description": (
                "Field goals attempted in matchup"
            ),
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".MATCHUP_FG_PCT"
            ),
            "description": (
                "Field goal pct in matchup"
            ),
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".MATCHUP_FG3M"
            ),
            "description": (
                "Three-pointers made in matchup"
            ),
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".MATCHUP_FG3A"
            ),
            "description": (
                "Three-pointers attempted"
            ),
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups"
                ".MATCHUP_FG3_PCT"
            ),
            "description": (
                "Three-point pct in matchup"
            ),
        },
    )
    help_blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.HELP_BLK"
            ),
            "description": "Help blocks in matchup",
        },
    )
    help_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.HELP_FGM"
            ),
            "description": (
                "Help field goals made"
            ),
        },
    )
    help_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.HELP_FGA"
            ),
            "description": (
                "Help field goals attempted"
            ),
        },
    )
    help_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.HELP_FG_PCT"
            ),
            "description": (
                "Help field goal percentage"
            ),
        },
    )
    matchup_ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_FTM"
            ),
            "description": (
                "Free throws made in matchup"
            ),
        },
    )
    matchup_fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.MATCHUP_FTA"
            ),
            "description": (
                "Free throws attempted"
            ),
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.SWITCHES_ON"
            ),
            "description": (
                "Number of switches onto player"
            ),
        },
    )
    pct_switched: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueSeasonMatchups"
                ".SeasonMatchups.PCT_SWITCHED"
            ),
            "description": (
                "Percentage of possessions switched"
            ),
        },
    )
