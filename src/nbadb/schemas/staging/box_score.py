from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingBoxScoreTraditionalPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.NICKNAME"),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.START_POSITION"),
            "description": ("Starting position (F/C/G)"),
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.COMMENT"),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.AST"),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.BLK"),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TOV"),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PF"),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLUS_MINUS"),
            "description": ("Plus-minus differential"),
        },
    )


class StagingBoxScoreTraditionalTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_NAME"),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.MIN"),
            "description": ("Total team minutes played"),
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.AST"),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.BLK"),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TOV"),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PF"),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PLUS_MINUS"),
            "description": ("Plus-minus differential"),
        },
    )


class StagingBoxScoreAdvancedPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_OFF_RATING"),
            "description": ("Estimated offensive rating"),
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OFF_RATING"),
            "description": "Offensive rating",
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_DEF_RATING"),
            "description": ("Estimated defensive rating"),
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DEF_RATING"),
            "description": "Defensive rating",
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_NET_RATING"),
            "description": ("Estimated net rating"),
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.NET_RATING"),
            "description": "Net rating",
        },
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_PCT"),
            "description": "Assist percentage",
        },
    )
    ast_tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_TOV"),
            "description": ("Assist to turnover ratio"),
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_RATIO"),
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OREB_PCT"),
            "description": ("Offensive rebound percentage"),
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DREB_PCT"),
            "description": ("Defensive rebound percentage"),
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.REB_PCT"),
            "description": ("Total rebound percentage"),
        },
    )
    tov_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TOV_PCT"),
            "description": "Turnover percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.EFG_PCT"),
            "description": ("Effective field goal percentage"),
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TS_PCT"),
            "description": "True shooting percentage",
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.USG_PCT"),
            "description": "Usage percentage",
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_USG_PCT"),
            "description": ("Estimated usage percentage"),
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_PACE"),
            "description": "Estimated pace",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PACE"),
            "description": "Pace factor",
        },
    )
    pace_per40: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PACE_PER40"),
            "description": "Pace per 40 minutes",
        },
    )
    poss: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.POSS"),
            "description": "Possessions",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PIE"),
            "description": ("Player impact estimate"),
        },
    )


class StagingBoxScoreHustlePlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    contested_shots: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS"),
            "description": "Contested shots",
        },
    )
    contested_shots_2pt: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS_2PT"),
            "description": ("Contested two-point shots"),
        },
    )
    contested_shots_3pt: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS_3PT"),
            "description": ("Contested three-point shots"),
        },
    )
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.DEFLECTIONS"),
            "description": "Deflections",
        },
    )
    charges_drawn: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CHARGES_DRAWN"),
            "description": "Charges drawn",
        },
    )
    screen_assists: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.SCREEN_ASSISTS"),
            "description": "Screen assists",
        },
    )
    screen_ast_pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.SCREEN_AST_PTS"),
            "description": ("Points from screen assists"),
        },
    )
    loose_balls_recovered: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.LOOSE_BALLS_RECOVERED"),
            "description": "Loose balls recovered",
        },
    )
    box_outs: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.BOX_OUTS"),
            "description": "Box outs",
        },
    )


class StagingBoxScorePlayerTrackSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    spd: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.SPD"),
            "description": "Average speed in mph",
        },
    )
    dist: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DIST"),
            "description": ("Distance covered in miles"),
        },
    )
    orbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.ORBC"),
            "description": ("Offensive rebound chances"),
        },
    )
    drbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DRBC"),
            "description": ("Defensive rebound chances"),
        },
    )
    rbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.RBC"),
            "description": ("Total rebound chances"),
        },
    )
    tchs: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TCHS"),
            "description": "Touches",
        },
    )
    sast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.SAST"),
            "description": "Secondary assists",
        },
    )
    ftast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.FTAST"),
            "description": ("Free throw assists"),
        },
    )
    pass_: float | None = pa.Field(
        nullable=True,
        ge=0,
        alias="pass",
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PASS"),
            "description": "Passes made",
        },
    )
    cfgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGM"),
            "description": ("Contested field goals made"),
        },
    )
    cfga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGA"),
            "description": ("Contested field goals attempted"),
        },
    )
    cfg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFG_PCT"),
            "description": ("Contested field goal percentage"),
        },
    )
    ufgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGM"),
            "description": ("Uncontested field goals made"),
        },
    )
    ufga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGA"),
            "description": ("Uncontested field goals attempted"),
        },
    )
    ufg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFG_PCT"),
            "description": ("Uncontested field goal percentage"),
        },
    )
    dfgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGM"),
            "description": ("Defended field goals made"),
        },
    )
    dfga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    dfg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFG_PCT"),
            "description": ("Defended field goal percentage"),
        },
    )


class StagingBoxScoreDefensivePlayerSchema(
    BaseSchema,
):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.MATCHUP_MIN"),
            "description": ("Minutes in matchup defense"),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PARTIAL_POSS"),
            "description": ("Partial possessions defended"),
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.SWITCHES_ON"),
            "description": ("Number of defensive switches"),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_PTS"),
            "description": ("Points allowed on defense"),
        },
    )
    def_fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FGM"),
            "description": ("Defended field goals made"),
        },
    )
    def_fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    def_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FG_PCT"),
            "description": ("Defended field goal percentage"),
        },
    )


class StagingBoxScoreFourFactorsPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.PLAYER_ID",
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.PLAYER_NAME",
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.MIN",
            "description": "Minutes played as string",
        },
    )
    effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.EFG_PCT",
            "description": "Effective field goal percentage",
        },
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.FTA_RATE",
            "description": "Free throw attempt rate",
        },
    )
    team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.TM_TOV_PCT",
            "description": "Team turnover percentage",
        },
    )
    offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OREB_PCT",
            "description": "Offensive rebound percentage",
        },
    )
    opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_EFG_PCT",
            "description": "Opponent effective field goal percentage",
        },
    )
    opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_FTA_RATE",
            "description": "Opponent free throw attempt rate",
        },
    )
    opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_TOV_PCT",
            "description": "Opponent team turnover percentage",
        },
    )
    opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_OREB_PCT",
            "description": "Opponent offensive rebound percentage",
        },
    )


class StagingBoxScoreFourFactorsTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.EFG_PCT",
            "description": "Effective field goal percentage",
        },
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.FTA_RATE",
            "description": "Free throw attempt rate",
        },
    )
    team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TM_TOV_PCT",
            "description": "Team turnover percentage",
        },
    )
    offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OREB_PCT",
            "description": "Offensive rebound percentage",
        },
    )
    opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_EFG_PCT",
            "description": "Opponent effective field goal percentage",
        },
    )
    opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_FTA_RATE",
            "description": "Opponent free throw attempt rate",
        },
    )
    opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_TOV_PCT",
            "description": "Opponent team turnover percentage",
        },
    )
    opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_OREB_PCT",
            "description": "Opponent offensive rebound percentage",
        },
    )
