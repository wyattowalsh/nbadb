from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingLeagueDashPlayerStatsSchema(BaseSchema):
    player_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    age: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.AGE"),
            "description": "Player age",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.GP"),
            "description": "Games played",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.W"),
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.L"),
            "description": "Losses",
        },
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.W_PCT"),
            "description": "Win percentage",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.MIN"),
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3M"),
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.AST"),
            "description": "Assists",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TOV"),
            "description": "Turnovers",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.BLK"),
            "description": "Blocks",
        },
    )
    blka: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.BLKA"),
            "description": "Blocked attempts",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PF"),
            "description": "Personal fouls",
        },
    )
    pfd: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PFD"),
            "description": "Personal fouls drawn",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PLUS_MINUS"),
            "description": "Plus-minus differential",
        },
    )
    nba_fantasy_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.NBA_FANTASY_PTS"),
            "description": "NBA fantasy points",
        },
    )
    dd2: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.DD2"),
            "description": "Double-doubles",
        },
    )
    td3: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TD3"),
            "description": "Triple-doubles",
        },
    )
    gp_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.GP_RANK"),
            "description": "Games played rank",
        },
    )
    w_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.W_RANK"),
            "description": "Wins rank",
        },
    )
    l_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.L_RANK"),
            "description": "Losses rank",
        },
    )
    w_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.W_PCT_RANK"),
            "description": "Win percentage rank",
        },
    )
    min_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.MIN_RANK"),
            "description": "Minutes played rank",
        },
    )
    fgm_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FGM_RANK"),
            "description": "Field goals made rank",
        },
    )
    fga_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FGA_RANK"),
            "description": "Field goals attempted rank",
        },
    )
    fg_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG_PCT_RANK"),
            "description": "Field goal percentage rank",
        },
    )
    fg3m_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3M_RANK"),
            "description": ("Three-point field goals made rank"),
        },
    )
    fg3a_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3A_RANK"),
            "description": ("Three-point field goals attempted rank"),
        },
    )
    fg3_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FG3_PCT_RANK"),
            "description": ("Three-point percentage rank"),
        },
    )
    ftm_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FTM_RANK"),
            "description": "Free throws made rank",
        },
    )
    fta_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FTA_RANK"),
            "description": "Free throws attempted rank",
        },
    )
    ft_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.FT_PCT_RANK"),
            "description": "Free throw percentage rank",
        },
    )
    oreb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.OREB_RANK"),
            "description": "Offensive rebounds rank",
        },
    )
    dreb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.DREB_RANK"),
            "description": "Defensive rebounds rank",
        },
    )
    reb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.REB_RANK"),
            "description": "Total rebounds rank",
        },
    )
    ast_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.AST_RANK"),
            "description": "Assists rank",
        },
    )
    tov_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TOV_RANK"),
            "description": "Turnovers rank",
        },
    )
    stl_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.STL_RANK"),
            "description": "Steals rank",
        },
    )
    blk_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.BLK_RANK"),
            "description": "Blocks rank",
        },
    )
    blka_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.BLKA_RANK"),
            "description": "Blocked attempts rank",
        },
    )
    pf_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PF_RANK"),
            "description": "Personal fouls rank",
        },
    )
    pfd_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PFD_RANK"),
            "description": "Personal fouls drawn rank",
        },
    )
    pts_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PTS_RANK"),
            "description": "Points scored rank",
        },
    )
    plus_minus_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.PLUS_MINUS_RANK"),
            "description": "Plus-minus rank",
        },
    )
    nba_fantasy_pts_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.NBA_FANTASY_PTS_RANK"),
            "description": "NBA fantasy points rank",
        },
    )
    dd2_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.DD2_RANK"),
            "description": "Double-doubles rank",
        },
    )
    td3_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.TD3_RANK"),
            "description": "Triple-doubles rank",
        },
    )
    cfid: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.CFID"),
            "description": "Custom filter identifier",
        },
    )
    cfparams: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashPlayerStats.LeagueDashPlayerStats.CFPARAMS"),
            "description": "Custom filter parameters",
        },
    )


class StagingLeagueDashTeamStatsSchema(BaseSchema):
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.TEAM_ID"),
            "description": "Unique team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.TEAM_NAME"),
            "description": "Team name",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.GP"),
            "description": "Games played",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.W"),
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.L"),
            "description": "Losses",
        },
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.W_PCT"),
            "description": "Win percentage",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.MIN"),
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.AST"),
            "description": "Assists",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.TOV"),
            "description": "Turnovers",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.BLK"),
            "description": "Blocks",
        },
    )
    blka: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.BLKA"),
            "description": "Blocked attempts",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PF"),
            "description": "Personal fouls",
        },
    )
    pfd: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PFD"),
            "description": "Personal fouls drawn",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PLUS_MINUS"),
            "description": "Plus-minus differential",
        },
    )
    gp_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.GP_RANK"),
            "description": "Games played rank",
        },
    )
    w_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.W_RANK"),
            "description": "Wins rank",
        },
    )
    l_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.L_RANK"),
            "description": "Losses rank",
        },
    )
    w_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.W_PCT_RANK"),
            "description": "Win percentage rank",
        },
    )
    min_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.MIN_RANK"),
            "description": "Minutes played rank",
        },
    )
    fgm_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FGM_RANK"),
            "description": "Field goals made rank",
        },
    )
    fga_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FGA_RANK"),
            "description": ("Field goals attempted rank"),
        },
    )
    fg_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG_PCT_RANK"),
            "description": ("Field goal percentage rank"),
        },
    )
    fg3m_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3M_RANK"),
            "description": ("Three-point field goals made rank"),
        },
    )
    fg3a_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3A_RANK"),
            "description": ("Three-point field goals attempted rank"),
        },
    )
    fg3_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FG3_PCT_RANK"),
            "description": ("Three-point percentage rank"),
        },
    )
    ftm_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FTM_RANK"),
            "description": "Free throws made rank",
        },
    )
    fta_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FTA_RANK"),
            "description": ("Free throws attempted rank"),
        },
    )
    ft_pct_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.FT_PCT_RANK"),
            "description": ("Free throw percentage rank"),
        },
    )
    oreb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.OREB_RANK"),
            "description": "Offensive rebounds rank",
        },
    )
    dreb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.DREB_RANK"),
            "description": "Defensive rebounds rank",
        },
    )
    reb_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.REB_RANK"),
            "description": "Total rebounds rank",
        },
    )
    ast_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.AST_RANK"),
            "description": "Assists rank",
        },
    )
    tov_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.TOV_RANK"),
            "description": "Turnovers rank",
        },
    )
    stl_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.STL_RANK"),
            "description": "Steals rank",
        },
    )
    blk_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.BLK_RANK"),
            "description": "Blocks rank",
        },
    )
    blka_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.BLKA_RANK"),
            "description": "Blocked attempts rank",
        },
    )
    pf_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PF_RANK"),
            "description": "Personal fouls rank",
        },
    )
    pfd_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PFD_RANK"),
            "description": "Personal fouls drawn rank",
        },
    )
    pts_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PTS_RANK"),
            "description": "Points scored rank",
        },
    )
    plus_minus_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.PLUS_MINUS_RANK"),
            "description": "Plus-minus rank",
        },
    )
    cfid: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.CFID"),
            "description": "Custom filter identifier",
        },
    )
    cfparams: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashTeamStats.LeagueDashTeamStats.CFPARAMS"),
            "description": "Custom filter parameters",
        },
    )


class StagingLeagueLineupVizSchema(BaseSchema):
    group_id: str = pa.Field(
        nullable=False,
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
        nullable=False,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
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
        ge=0,
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
        ge=0.0,
        le=1.0,
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
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.TM_AST_PCT"),
            "description": "Team assist percentage",
        },
    )
    pct_fga_2pt: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_FGA_2PT"),
            "description": ("Percentage of field goal attempts from two-point range"),
        },
    )
    pct_fga_3pt: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_FGA_3PT"),
            "description": ("Percentage of field goal attempts from three-point range"),
        },
    )
    pct_pts_2pt_mr: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_2PT_MR"),
            "description": ("Percentage of points from mid-range two-pointers"),
        },
    )
    pct_pts_fb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_FB"),
            "description": ("Percentage of points from fast breaks"),
        },
    )
    pct_pts_ft: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_FT"),
            "description": ("Percentage of points from free throws"),
        },
    )
    pct_pts_paint: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_PTS_PAINT"),
            "description": ("Percentage of points in the paint"),
        },
    )
    pct_ast_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_AST_FGM"),
            "description": ("Percentage of assisted field goals"),
        },
    )
    pct_uast_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.PCT_UAST_FGM"),
            "description": ("Percentage of unassisted field goals"),
        },
    )
    opp_fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_FG3_PCT"),
            "description": ("Opponent three-point percentage"),
        },
    )
    opp_efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
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
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueLineupViz.LeagueLineupViz.OPP_TOV_PCT"),
            "description": ("Opponent turnover percentage"),
        },
    )
