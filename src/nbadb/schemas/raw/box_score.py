from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawBoxScoreTraditionalPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FGA"
            ),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FG3M"
            ),
            "description": (
                "Three-point field goals made"
            ),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FG3A"
            ),
            "description": (
                "Three-point field goals attempted"
            ),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FG3_PCT"
            ),
            "description": (
                "Three-point field goal percentage"
            ),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FTM"
            ),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FTA"
            ),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.OREB"
            ),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.DREB"
            ),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.REB"
            ),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.AST"
            ),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.STL"
            ),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.BLK"
            ),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.TOV"
            ),
            "description": (
                "Turnovers (alias TO in some versions)"
            ),
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.PF"
            ),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.PTS"
            ),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".PlayerStats.PLUS_MINUS"
            ),
            "description": "Plus-minus differential",
        },
    )


class RawBoxScoreTraditionalTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.MIN"
            ),
            "description": "Total team minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FGA"
            ),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FG3M"
            ),
            "description": (
                "Three-point field goals made"
            ),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FG3A"
            ),
            "description": (
                "Three-point field goals attempted"
            ),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FG3_PCT"
            ),
            "description": (
                "Three-point field goal percentage"
            ),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FTM"
            ),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FTA"
            ),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.OREB"
            ),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.DREB"
            ),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.REB"
            ),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.AST"
            ),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.STL"
            ),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.BLK"
            ),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.TOV"
            ),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.PF"
            ),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.PTS"
            ),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreTraditionalV3"
                ".TeamStats.PLUS_MINUS"
            ),
            "description": "Plus-minus differential",
        },
    )


class RawBoxScoreAdvancedPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.E_OFF_RATING"
            ),
            "description": (
                "Estimated offensive rating"
            ),
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.OFF_RATING"
            ),
            "description": "Offensive rating",
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.E_DEF_RATING"
            ),
            "description": (
                "Estimated defensive rating"
            ),
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.DEF_RATING"
            ),
            "description": "Defensive rating",
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.E_NET_RATING"
            ),
            "description": "Estimated net rating",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.NET_RATING"
            ),
            "description": "Net rating",
        },
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_PCT"
            ),
            "description": "Assist percentage",
        },
    )
    ast_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_TOV"
            ),
            "description": (
                "Assist-to-turnover ratio"
            ),
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.AST_RATIO"
            ),
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.OREB_PCT"
            ),
            "description": (
                "Offensive rebound percentage"
            ),
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.DREB_PCT"
            ),
            "description": (
                "Defensive rebound percentage"
            ),
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.REB_PCT"
            ),
            "description": "Total rebound percentage",
        },
    )
    tm_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TM_TOV_PCT"
            ),
            "description": "Team turnover percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.EFG_PCT"
            ),
            "description": (
                "Effective field goal percentage"
            ),
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.TS_PCT"
            ),
            "description": "True shooting percentage",
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.USG_PCT"
            ),
            "description": "Usage percentage",
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.E_USG_PCT"
            ),
            "description": (
                "Estimated usage percentage"
            ),
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.E_PACE"
            ),
            "description": "Estimated pace",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PACE"
            ),
            "description": "Pace",
        },
    )
    pace_per40: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PACE_PER40"
            ),
            "description": "Pace per 40 minutes",
        },
    )
    poss: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.POSS"
            ),
            "description": "Possessions",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreAdvancedV3"
                ".PlayerStats.PIE"
            ),
            "description": (
                "Player impact estimate"
            ),
        },
    )


class RawBoxScoreMiscPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PTS_OFF_TOV"
            ),
            "description": (
                "Points off turnovers"
            ),
        },
    )
    second_chance_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.SECOND_CHANCE_PTS"
            ),
            "description": "Second chance points",
        },
    )
    fbps: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.FBPS"
            ),
            "description": "Fast break points",
        },
    )
    pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PITP"
            ),
            "description": "Points in the paint",
        },
    )
    opp_pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.OPP_PTS_OFF_TOV"
            ),
            "description": (
                "Opponent points off turnovers"
            ),
        },
    )
    opp_second_chance_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats"
                ".OPP_SECOND_CHANCE_PTS"
            ),
            "description": (
                "Opponent second chance points"
            ),
        },
    )
    opp_fbps: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.OPP_FBPS"
            ),
            "description": (
                "Opponent fast break points"
            ),
        },
    )
    opp_pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.OPP_PITP"
            ),
            "description": (
                "Opponent points in the paint"
            ),
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.BLK"
            ),
            "description": "Blocks",
        },
    )
    blka: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.BLKA"
            ),
            "description": "Blocked shot attempts",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PF"
            ),
            "description": "Personal fouls",
        },
    )
    pfd: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreMiscV3"
                ".PlayerStats.PFD"
            ),
            "description": "Personal fouls drawn",
        },
    )


class RawBoxScoreScoringPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    pct_fga_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_FGA_2PT"
            ),
            "description": (
                "Percent of FGA that are 2-pointers"
            ),
        },
    )
    pct_fga_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_FGA_3PT"
            ),
            "description": (
                "Percent of FGA that are 3-pointers"
            ),
        },
    )
    pct_pts_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_2PT"
            ),
            "description": (
                "Percent of points from 2-pointers"
            ),
        },
    )
    pct_pts_2pt_mr: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_2PT_MR"
            ),
            "description": (
                "Percent of points from mid-range"
            ),
        },
    )
    pct_pts_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_3PT"
            ),
            "description": (
                "Percent of points from 3-pointers"
            ),
        },
    )
    pct_pts_fb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_FB"
            ),
            "description": (
                "Percent of points from fast breaks"
            ),
        },
    )
    pct_pts_ft: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_FT"
            ),
            "description": (
                "Percent of points from free throws"
            ),
        },
    )
    pct_pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_OFF_TOV"
            ),
            "description": (
                "Percent of points off turnovers"
            ),
        },
    )
    pct_pts_pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_PTS_PITP"
            ),
            "description": (
                "Percent of points in the paint"
            ),
        },
    )
    pct_ast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_AST_2PM"
            ),
            "description": (
                "Percent of assisted 2-point makes"
            ),
        },
    )
    pct_uast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_UAST_2PM"
            ),
            "description": (
                "Percent of unassisted 2-point makes"
            ),
        },
    )
    pct_ast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_AST_3PM"
            ),
            "description": (
                "Percent of assisted 3-point makes"
            ),
        },
    )
    pct_uast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_UAST_3PM"
            ),
            "description": (
                "Percent of unassisted 3-point makes"
            ),
        },
    )
    pct_ast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_AST_FGM"
            ),
            "description": (
                "Percent of assisted field goal makes"
            ),
        },
    )
    pct_uast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreScoringV3"
                ".PlayerStats.PCT_UAST_FGM"
            ),
            "description": (
                "Percent of unassisted FG makes"
            ),
        },
    )


class RawBoxScoreUsagePlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.USG_PCT"
            ),
            "description": "Usage percentage",
        },
    )
    pct_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FGM"
            ),
            "description": (
                "Percent of team field goals made"
            ),
        },
    )
    pct_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FGA"
            ),
            "description": (
                "Percent of team FG attempted"
            ),
        },
    )
    pct_fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FG3M"
            ),
            "description": (
                "Percent of team 3-point FG made"
            ),
        },
    )
    pct_fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FG3A"
            ),
            "description": (
                "Percent of team 3-point FG attempted"
            ),
        },
    )
    pct_ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FTM"
            ),
            "description": (
                "Percent of team free throws made"
            ),
        },
    )
    pct_fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_FTA"
            ),
            "description": (
                "Percent of team FT attempted"
            ),
        },
    )
    pct_oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_OREB"
            ),
            "description": (
                "Percent of team offensive rebounds"
            ),
        },
    )
    pct_dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_DREB"
            ),
            "description": (
                "Percent of team defensive rebounds"
            ),
        },
    )
    pct_reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_REB"
            ),
            "description": (
                "Percent of team total rebounds"
            ),
        },
    )
    pct_ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_AST"
            ),
            "description": (
                "Percent of team assists"
            ),
        },
    )
    pct_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_TOV"
            ),
            "description": (
                "Percent of team turnovers"
            ),
        },
    )
    pct_stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_STL"
            ),
            "description": (
                "Percent of team steals"
            ),
        },
    )
    pct_blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_BLK"
            ),
            "description": (
                "Percent of team blocks"
            ),
        },
    )
    pct_blka: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_BLKA"
            ),
            "description": (
                "Percent of team blocked attempts"
            ),
        },
    )
    pct_pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_PF"
            ),
            "description": (
                "Percent of team personal fouls"
            ),
        },
    )
    pct_pfd: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_PFD"
            ),
            "description": (
                "Percent of team personal fouls drawn"
            ),
        },
    )
    pct_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreUsageV3"
                ".PlayerStats.PCT_PTS"
            ),
            "description": (
                "Percent of team points"
            ),
        },
    )


class RawBoxScoreFourFactorsPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.EFG_PCT"
            ),
            "description": (
                "Effective field goal percentage"
            ),
        },
    )
    fta_rate: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.FTA_RATE"
            ),
            "description": "Free throw attempt rate",
        },
    )
    tm_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.TM_TOV_PCT"
            ),
            "description": "Team turnover percentage",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.OREB_PCT"
            ),
            "description": (
                "Offensive rebound percentage"
            ),
        },
    )
    opp_efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.OPP_EFG_PCT"
            ),
            "description": (
                "Opponent effective FG percentage"
            ),
        },
    )
    opp_fta_rate: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.OPP_FTA_RATE"
            ),
            "description": (
                "Opponent free throw attempt rate"
            ),
        },
    )
    opp_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.OPP_TOV_PCT"
            ),
            "description": (
                "Opponent turnover percentage"
            ),
        },
    )
    opp_oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreFourFactorsV3"
                ".PlayerStats.OPP_OREB_PCT"
            ),
            "description": (
                "Opponent offensive rebound pct"
            ),
        },
    )


class RawBoxScoreHustlePlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    contested_shots: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.CONTESTED_SHOTS"
            ),
            "description": "Total contested shots",
        },
    )
    contested_shots_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.CONTESTED_SHOTS_2PT"
            ),
            "description": (
                "Contested 2-point shots"
            ),
        },
    )
    contested_shots_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.CONTESTED_SHOTS_3PT"
            ),
            "description": (
                "Contested 3-point shots"
            ),
        },
    )
    deflections: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.DEFLECTIONS"
            ),
            "description": "Deflections",
        },
    )
    charges_drawn: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.CHARGES_DRAWN"
            ),
            "description": "Charges drawn",
        },
    )
    screen_assists: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.SCREEN_ASSISTS"
            ),
            "description": "Screen assists",
        },
    )
    screen_ast_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.SCREEN_AST_PTS"
            ),
            "description": (
                "Points from screen assists"
            ),
        },
    )
    loose_balls_recovered_off: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "BoxScoreHustleV2"
                    ".PlayerStats"
                    ".LOOSE_BALLS_RECOVERED_OFF"
                ),
                "description": (
                    "Offensive loose balls recovered"
                ),
            },
        )
    )
    loose_balls_recovered_def: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "BoxScoreHustleV2"
                    ".PlayerStats"
                    ".LOOSE_BALLS_RECOVERED_DEF"
                ),
                "description": (
                    "Defensive loose balls recovered"
                ),
            },
        )
    )
    loose_balls_recovered: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".LOOSE_BALLS_RECOVERED"
            ),
            "description": (
                "Total loose balls recovered"
            ),
        },
    )
    off_boxouts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.OFF_BOXOUTS"
            ),
            "description": "Offensive box outs",
        },
    )
    def_boxouts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.DEF_BOXOUTS"
            ),
            "description": "Defensive box outs",
        },
    )
    box_outs: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.BOX_OUTS"
            ),
            "description": "Total box outs",
        },
    )


class RawBoxScorePlayerTrackSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.NICKNAME"
            ),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    spd: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.SPD"
            ),
            "description": "Average speed",
        },
    )
    dist: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.DIST"
            ),
            "description": "Distance covered",
        },
    )
    orbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.ORBC"
            ),
            "description": (
                "Offensive rebound chances"
            ),
        },
    )
    drbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.DRBC"
            ),
            "description": (
                "Defensive rebound chances"
            ),
        },
    )
    rbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.RBC"
            ),
            "description": "Total rebound chances",
        },
    )
    tchs: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.TCHS"
            ),
            "description": "Touches",
        },
    )
    sast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.SAST"
            ),
            "description": "Secondary assists",
        },
    )
    ftast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.FTAST"
            ),
            "description": (
                "Free throw assists"
            ),
        },
    )
    pass_: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.PASS"
            ),
            "description": "Passes made",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.AST"
            ),
            "description": "Assists",
        },
    )
    cfgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.CFGM"
            ),
            "description": (
                "Contested field goals made"
            ),
        },
    )
    cfga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.CFGA"
            ),
            "description": (
                "Contested field goals attempted"
            ),
        },
    )
    cfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.CFG_PCT"
            ),
            "description": (
                "Contested field goal percentage"
            ),
        },
    )
    ufgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.UFGM"
            ),
            "description": (
                "Uncontested field goals made"
            ),
        },
    )
    ufga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.UFGA"
            ),
            "description": (
                "Uncontested FG attempted"
            ),
        },
    )
    ufg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.UFG_PCT"
            ),
            "description": (
                "Uncontested field goal percentage"
            ),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    dfgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.DFGM"
            ),
            "description": (
                "Defended field goals made"
            ),
        },
    )
    dfga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.DFGA"
            ),
            "description": (
                "Defended field goals attempted"
            ),
        },
    )
    dfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScorePlayerTrackV3"
                ".PlayerStats.DFG_PCT"
            ),
            "description": (
                "Defended field goal percentage"
            ),
        },
    )


class RawBoxScoreDefensivePlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.START_POSITION"
            ),
            "description": "Starting position (F/C/G)",
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.COMMENT"
            ),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MIN"
            ),
            "description": "Minutes played as string",
        },
    )
    matchup_min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_MIN"
            ),
            "description": (
                "Matchup minutes as string"
            ),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.PLAYER_PTS"
            ),
            "description": (
                "Points scored by player"
            ),
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.TEAM_PTS"
            ),
            "description": (
                "Points scored by team"
            ),
        },
    )
    matchup_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_PCT"
            ),
            "description": (
                "Matchup time percentage"
            ),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.PARTIAL_POSS"
            ),
            "description": "Partial possessions",
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.SWITCHES_ON"
            ),
            "description": (
                "Switches drawn on defense"
            ),
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_AST"
            ),
            "description": (
                "Assists allowed in matchup"
            ),
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_TOV"
            ),
            "description": (
                "Turnovers forced in matchup"
            ),
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.STL"
            ),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.BLK"
            ),
            "description": "Blocks",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FGM"
            ),
            "description": (
                "FG made allowed in matchup"
            ),
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FGA"
            ),
            "description": (
                "FG attempted in matchup"
            ),
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FG_PCT"
            ),
            "description": (
                "FG percentage in matchup"
            ),
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FG3M"
            ),
            "description": (
                "3-point FG made in matchup"
            ),
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FG3A"
            ),
            "description": (
                "3-point FG attempted in matchup"
            ),
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "BoxScoreDefensiveV2"
                ".PlayerStats.MATCHUP_FG3_PCT"
            ),
            "description": (
                "3-point FG pct in matchup"
            ),
        },
    )
