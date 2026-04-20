from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema
from nbadb.schemas.staging.misc import StagingWinProbabilitySchema


class _PlayerStatLineSchema(BaseSchema):
    gp: int | None = pa.Field(nullable=True, ge=0)
    gs: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class _PlayerCareerRecordSchema(_PlayerStatLineSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    season_id: str | None = pa.Field(nullable=True)
    league_id: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    organization_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    school_name: str | None = pa.Field(nullable=True)
    player_age: float | None = pa.Field(nullable=True, ge=0.0)


class _PlayerSeasonRanksSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    season_id: str | None = pa.Field(nullable=True)
    league_id: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    player_age: float | None = pa.Field(nullable=True, ge=0.0)
    gp: int | None = pa.Field(nullable=True, ge=0)
    gs: int | None = pa.Field(nullable=True, ge=0)
    rank_min: int | None = pa.Field(nullable=True, ge=0)
    rank_fgm: int | None = pa.Field(nullable=True, ge=0)
    rank_fga: int | None = pa.Field(nullable=True, ge=0)
    rank_fg_pct: int | None = pa.Field(nullable=True, ge=0)
    rank_fg3m: int | None = pa.Field(nullable=True, ge=0)
    rank_fg3a: int | None = pa.Field(nullable=True, ge=0)
    rank_fg3_pct: int | None = pa.Field(nullable=True, ge=0)
    rank_ftm: int | None = pa.Field(nullable=True, ge=0)
    rank_fta: int | None = pa.Field(nullable=True, ge=0)
    rank_ft_pct: int | None = pa.Field(nullable=True, ge=0)
    rank_oreb: int | None = pa.Field(nullable=True, ge=0)
    rank_dreb: int | None = pa.Field(nullable=True, ge=0)
    rank_reb: int | None = pa.Field(nullable=True, ge=0)
    rank_ast: int | None = pa.Field(nullable=True, ge=0)
    rank_stl: int | None = pa.Field(nullable=True, ge=0)
    rank_blk: int | None = pa.Field(nullable=True, ge=0)
    rank_tov: int | None = pa.Field(nullable=True, ge=0)
    rank_pts: int | None = pa.Field(nullable=True, ge=0)
    rank_eff: int | None = pa.Field(nullable=True, ge=0)


class _PlayerProfileCareerHighsSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    game_id: str | None = pa.Field(nullable=True)
    game_date: str | None = pa.Field(nullable=True)
    vs_team_id: int | None = pa.Field(nullable=True, gt=0)
    vs_team_city: str | None = pa.Field(nullable=True)
    vs_team_name: str | None = pa.Field(nullable=True)
    vs_team_abbreviation: str | None = pa.Field(nullable=True)
    stat: str | None = pa.Field(nullable=True)
    stat_value: float | None = pa.Field(nullable=True)
    stats_value: float | None = pa.Field(nullable=True)
    stat_order: int | None = pa.Field(nullable=True, ge=0)
    date_est: str | None = pa.Field(nullable=True)


class _PlayerProfileNextGameSchema(BaseSchema):
    game_id: str | None = pa.Field(nullable=True)
    game_date: str | None = pa.Field(nullable=True)
    game_time: str | None = pa.Field(nullable=True)
    location: str | None = pa.Field(nullable=True)
    player_team_id: int | None = pa.Field(nullable=True, gt=0)
    player_team_city: str | None = pa.Field(nullable=True)
    player_team_nickname: str | None = pa.Field(nullable=True)
    player_team_abbreviation: str | None = pa.Field(nullable=True)
    vs_team_id: int | None = pa.Field(nullable=True, gt=0)
    vs_team_city: str | None = pa.Field(nullable=True)
    vs_team_nickname: str | None = pa.Field(nullable=True)
    vs_team_abbreviation: str | None = pa.Field(nullable=True)


class _PlayerCollegeRollupSchema(_PlayerStatLineSchema):
    region: str | None = pa.Field(nullable=True)
    seed: int | None = pa.Field(nullable=True, ge=0)
    college: str | None = pa.Field(nullable=True)
    players: int | None = pa.Field(nullable=True, ge=0)


class _PlayerMatchupCompareSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    description: str | None = pa.Field(nullable=True)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)


class _PlayerVsPlayerStatsSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_value: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0, alias="l")
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)


class _PlayerVsPlayerShotSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_value: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)


class _PvpPlayerInfoSchema(BaseSchema):
    person_id: int = pa.Field(nullable=False, gt=0)
    first_name: str | None = pa.Field(nullable=True)
    last_name: str | None = pa.Field(nullable=True)
    display_first_last: str | None = pa.Field(nullable=True)
    display_last_comma_first: str | None = pa.Field(nullable=True)
    display_fi_last: str | None = pa.Field(nullable=True)
    birthdate: str | None = pa.Field(nullable=True)
    school: str | None = pa.Field(nullable=True)
    country: str | None = pa.Field(nullable=True)
    last_affiliation: str | None = pa.Field(nullable=True)


class _PlayerPtPassSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name_last_first: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    pass_type: str | None = pa.Field(nullable=True)
    g: int | None = pa.Field(nullable=True, ge=0)
    pass_to: str | None = pa.Field(nullable=True)
    pass_from: str | None = pa.Field(nullable=True)
    pass_teammate_player_id: int | None = pa.Field(nullable=True, gt=0)
    frequency: float | None = pa.Field(nullable=True, ge=0.0)
    pass_: int | None = pa.Field(nullable=True, ge=0, alias="pass")
    ast: int | None = pa.Field(nullable=True, ge=0)
    fgm: int | None = pa.Field(nullable=True, ge=0)
    fga: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg2m: int | None = pa.Field(nullable=True, ge=0)
    fg2a: int | None = pa.Field(nullable=True, ge=0)
    fg2_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: int | None = pa.Field(nullable=True, ge=0)
    fg3a: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    season_type: str | None = pa.Field(nullable=True)


class _PlayerPtRebSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name_last_first: str | None = pa.Field(nullable=True)
    sort_order: int | None = pa.Field(nullable=True, ge=0)
    g: int | None = pa.Field(nullable=True, ge=0)
    reb_num_contesting_range: str | None = pa.Field(nullable=True)
    overall: str | None = pa.Field(nullable=True)
    reb_dist_range: str | None = pa.Field(nullable=True)
    shot_dist_range: str | None = pa.Field(nullable=True)
    shot_type_range: str | None = pa.Field(nullable=True)
    reb_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    oreb: int | None = pa.Field(nullable=True, ge=0)
    dreb: int | None = pa.Field(nullable=True, ge=0)
    reb: int | None = pa.Field(nullable=True, ge=0)
    c_oreb: int | None = pa.Field(nullable=True, ge=0)
    c_dreb: int | None = pa.Field(nullable=True, ge=0)
    c_reb: int | None = pa.Field(nullable=True, ge=0)
    c_reb_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    uc_oreb: int | None = pa.Field(nullable=True, ge=0)
    uc_dreb: int | None = pa.Field(nullable=True, ge=0)
    uc_reb: int | None = pa.Field(nullable=True, ge=0)
    uc_reb_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    season_type: str | None = pa.Field(nullable=True)


class _PlayerPtShotsSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name_last_first: str | None = pa.Field(nullable=True)
    sort_order: int | None = pa.Field(nullable=True, ge=0)
    gp: int | None = pa.Field(nullable=True, ge=0)
    g: int | None = pa.Field(nullable=True, ge=0)
    close_def_dist_range: str | None = pa.Field(nullable=True)
    dribble_range: str | None = pa.Field(nullable=True)
    shot_type: str | None = pa.Field(nullable=True)
    shot_clock_range: str | None = pa.Field(nullable=True)
    touch_time_range: str | None = pa.Field(nullable=True)
    fga_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: int | None = pa.Field(nullable=True, ge=0)
    fga: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg2a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fg2m: int | None = pa.Field(nullable=True, ge=0)
    fg2a: int | None = pa.Field(nullable=True, ge=0)
    fg2_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m: int | None = pa.Field(nullable=True, ge=0)
    fg3a: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    season_type: str | None = pa.Field(nullable=True)


class _PlayerTrackingSchema(BaseSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0, alias="l")
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    e_off_rating: float | None = pa.Field(nullable=True)
    e_def_rating: float | None = pa.Field(nullable=True)
    e_net_rating: float | None = pa.Field(nullable=True)
    e_ast_ratio: float | None = pa.Field(nullable=True)
    e_oreb_pct: float | None = pa.Field(nullable=True)
    e_dreb_pct: float | None = pa.Field(nullable=True)
    e_reb_pct: float | None = pa.Field(nullable=True)
    e_tov_pct: float | None = pa.Field(nullable=True)
    e_usg_pct: float | None = pa.Field(nullable=True)
    e_pace: float | None = pa.Field(nullable=True)
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    e_off_rating_rank: int | None = pa.Field(nullable=True, ge=0)
    e_def_rating_rank: int | None = pa.Field(nullable=True, ge=0)
    e_net_rating_rank: int | None = pa.Field(nullable=True, ge=0)
    e_ast_ratio_rank: int | None = pa.Field(nullable=True, ge=0)
    e_oreb_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_dreb_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_reb_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_tov_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_usg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_pace_rank: int | None = pa.Field(nullable=True, ge=0)
    season_year: str | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)


class _PlayerGameLogsSchema(BaseSchema):
    season_id: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field(nullable=False)
    game_date: str | None = pa.Field(nullable=True)
    matchup: str | None = pa.Field(nullable=True)
    wl: str | None = pa.Field(nullable=True)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    dd2: int | None = pa.Field(nullable=True, ge=0)
    td3: int | None = pa.Field(nullable=True, ge=0)
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)
    nba_fantasy_pts_rank: int | None = pa.Field(nullable=True, ge=0)
    dd2_rank: int | None = pa.Field(nullable=True, ge=0)
    td3_rank: int | None = pa.Field(nullable=True, ge=0)
    video_available: int | None = pa.Field(nullable=True, ge=0)
    season_type: str | None = pa.Field(nullable=True)


class StagingLeaguePlayerOnDetailsSchema(_PlayerVsPlayerStatsSchema):
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)


class StagingPlayerOnDetailsSchema(StagingLeaguePlayerOnDetailsSchema):
    pass


class StagingPlayerCareerByCollegeSchema(_PlayerStatLineSchema):
    player_id: int = pa.Field(nullable=False, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    college: str | None = pa.Field(nullable=True)


class StagingPlayerCollegeSchema(StagingPlayerCareerByCollegeSchema):
    pass


class StagingPlayerCareerAllstarSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerCollegeSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerPostseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerRegularSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerTotalAllstarSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerTotalCollegeSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerTotalPostseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerCareerTotalRegularSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerSeasonRanksPostseasonSchema(_PlayerSeasonRanksSchema):
    pass


class StagingPlayerSeasonRanksRegularSchema(_PlayerSeasonRanksSchema):
    pass


class StagingPlayerCollegeRollupSchema(_PlayerCollegeRollupSchema):
    pass


class StagingPlayerCareerByCollegeRollupSchema(_PlayerCollegeRollupSchema):
    pass


class StagingCollegeRollupEastSchema(_PlayerCollegeRollupSchema):
    pass


class StagingCollegeRollupMidwestSchema(_PlayerCollegeRollupSchema):
    pass


class StagingCollegeRollupSouthSchema(_PlayerCollegeRollupSchema):
    pass


class StagingCollegeRollupWestSchema(_PlayerCollegeRollupSchema):
    pass


class StagingPlayerCompareSchema(_PlayerMatchupCompareSchema):
    pass


class StagingPlayerCompareIndividualSchema(_PlayerMatchupCompareSchema):
    pass


class StagingPlayerCompareOverallSchema(_PlayerMatchupCompareSchema):
    pass


class StagingPlayerPtPassSchema(_PlayerPtPassSchema):
    pass


class StagingPlayerPtPassReceivedSchema(_PlayerPtPassSchema):
    pass


class StagingPlayerPtRebSchema(_PlayerPtRebSchema):
    pass


class StagingPlayerPtRebDistanceSchema(_PlayerPtRebSchema):
    pass


class StagingPlayerPtRebOverallSchema(_PlayerPtRebSchema):
    pass


class StagingPlayerPtRebShotDistSchema(_PlayerPtRebSchema):
    pass


class StagingPlayerPtRebShotTypeSchema(_PlayerPtRebSchema):
    pass


class StagingPlayerPtShotDefendSchema(BaseSchema):
    close_def_person_id: int = pa.Field(nullable=False, gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)
    g: int | None = pa.Field(nullable=True, ge=0)
    defense_category: str | None = pa.Field(nullable=True)
    freq: float | None = pa.Field(nullable=True, ge=0.0)
    d_fgm: int | None = pa.Field(nullable=True, ge=0)
    d_fga: int | None = pa.Field(nullable=True, ge=0)
    d_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    normal_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    pct_plusminus: float | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)


class StagingPlayerPtShotsSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsClosestDefSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsDribbleSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsGeneralSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsOverallSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsShotClockSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerPtShotsTouchTimeSchema(_PlayerPtShotsSchema):
    pass


class StagingPlayerTrackingSchema(_PlayerTrackingSchema):
    pass


class StagingPlayerGameLogsSchema(_PlayerGameLogsSchema):
    pass


class StagingPlayerGameLogsV2Schema(_PlayerGameLogsSchema):
    pass


class StagingPlayerNextGamesSchema(_PlayerProfileNextGameSchema):
    home_team_id: int | None = pa.Field(nullable=True, gt=0)
    visitor_team_id: int | None = pa.Field(nullable=True, gt=0)
    home_team_name: str | None = pa.Field(nullable=True)
    visitor_team_name: str | None = pa.Field(nullable=True)
    home_team_abbreviation: str | None = pa.Field(nullable=True)
    visitor_team_abbreviation: str | None = pa.Field(nullable=True)
    home_team_nickname: str | None = pa.Field(nullable=True)
    visitor_team_nickname: str | None = pa.Field(nullable=True)
    home_wl: str | None = pa.Field(nullable=True)
    visitor_wl: str | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)


class StagingPlayerProfileAllstarSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileCareerHighsSchema(_PlayerProfileCareerHighsSchema):
    pass


class StagingPlayerProfileCollegeSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileNextGameSchema(_PlayerProfileNextGameSchema):
    pass


class StagingPlayerProfilePostseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfilePreseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileRanksPostseasonSchema(_PlayerSeasonRanksSchema):
    pass


class StagingPlayerProfileRanksRegularSchema(_PlayerSeasonRanksSchema):
    pass


class StagingPlayerProfileRegularSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileSeasonHighsSchema(_PlayerProfileCareerHighsSchema):
    pass


class StagingPlayerProfileTotalAllstarSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileTotalCollegeSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileTotalPostseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileTotalPreseasonSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerProfileTotalRegularSchema(_PlayerCareerRecordSchema):
    pass


class StagingPlayerStreakFinderSchema(BaseSchema):
    player_name_last_first: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    gamestreak: str | None = pa.Field(nullable=True)
    startdate: str | None = pa.Field(nullable=True)
    enddate: str | None = pa.Field(nullable=True)
    activestreak: str | None = pa.Field(nullable=True)
    numseasons: int | None = pa.Field(nullable=True, ge=0)
    lastseason: str | None = pa.Field(nullable=True)
    firstseason: str | None = pa.Field(nullable=True)


class StagingPlayerGameStreakFinderSchema(StagingPlayerStreakFinderSchema):
    pass


class StagingPlayerVsPlayerSchema(_PlayerVsPlayerStatsSchema):
    pass


class StagingPvpOnOffCourtSchema(_PlayerVsPlayerStatsSchema):
    pass


class StagingPvpOverallSchema(_PlayerVsPlayerStatsSchema):
    pass


class StagingPvpPlayerInfoSchema(_PvpPlayerInfoSchema):
    pass


class StagingPvpShotAreaOffSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpShotAreaOnSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpShotAreaOverallSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpShotDistOffSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpShotDistOnSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpShotDistOverallSchema(_PlayerVsPlayerShotSchema):
    pass


class StagingPvpVsPlayerInfoSchema(_PvpPlayerInfoSchema):
    pass


class StagingWinProbPbpSchema(StagingWinProbabilitySchema):
    pass
