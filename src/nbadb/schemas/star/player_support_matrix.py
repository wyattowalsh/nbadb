from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.staging.player_support_matrix import (
    StagingPlayerNextGamesSchema,
    StagingPlayerPtPassSchema,
    StagingPlayerPtShotDefendSchema,
    _PlayerCareerRecordSchema,
    _PlayerCollegeRollupSchema,
    _PlayerGameLogsSchema,
    _PlayerPtRebSchema,
    _PlayerPtShotsSchema,
    _PlayerSeasonRanksSchema,
)


class FactPlayerCareerSchema(_PlayerCareerRecordSchema):
    career_type: str = pa.Field(
        nullable=False,
        isin=[
            "regular",
            "postseason",
            "total_allstar",
            "total_college",
            "allstar",
            "college",
            "season_regular",
            "season_postseason",
        ],
    )


class FactPlayerSeasonRanksSchema(_PlayerSeasonRanksSchema):
    rank_type: str = pa.Field(nullable=False, isin=["regular", "postseason"])


class FactCollegeRollupSchema(_PlayerCollegeRollupSchema):
    rollup_type: str = pa.Field(
        nullable=False,
        isin=["college", "career_by_college", "east", "midwest", "south", "west"],
    )


class FactPlayerMatchupsSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    description: str | None = pa.Field(nullable=True)
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
    matchup_type: str = pa.Field(nullable=False, isin=["head_to_head", "compare"])


class FactPlayerPtTrackingSchema(BaseSchema):
    player_id: int | None = pa.Field(nullable=True, gt=0)
    close_def_person_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    player_name_last_first: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    pass_type: str | None = pa.Field(nullable=True)
    g: int | None = pa.Field(nullable=True, ge=0)
    sort_order: int | None = pa.Field(nullable=True, ge=0)
    pass_to: str | None = pa.Field(nullable=True)
    pass_from: str | None = pa.Field(nullable=True)
    pass_teammate_player_id: int | None = pa.Field(nullable=True, gt=0)
    frequency: float | None = pa.Field(nullable=True, ge=0.0)
    pass_: int | None = pa.Field(nullable=True, ge=0, alias="pass")
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg2m: float | None = pa.Field(nullable=True, ge=0.0)
    fg2a: float | None = pa.Field(nullable=True, ge=0.0)
    fg2_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    reb_num_contesting_range: str | None = pa.Field(nullable=True)
    overall: str | None = pa.Field(nullable=True)
    reb_dist_range: str | None = pa.Field(nullable=True)
    shot_dist_range: str | None = pa.Field(nullable=True)
    shot_type_range: str | None = pa.Field(nullable=True)
    reb_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    c_oreb: float | None = pa.Field(nullable=True, ge=0.0)
    c_dreb: float | None = pa.Field(nullable=True, ge=0.0)
    c_reb: float | None = pa.Field(nullable=True, ge=0.0)
    c_reb_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    uc_oreb: float | None = pa.Field(nullable=True, ge=0.0)
    uc_dreb: float | None = pa.Field(nullable=True, ge=0.0)
    uc_reb: float | None = pa.Field(nullable=True, ge=0.0)
    uc_reb_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    gp: int | None = pa.Field(nullable=True, ge=0)
    close_def_dist_range: str | None = pa.Field(nullable=True)
    dribble_range: str | None = pa.Field(nullable=True)
    shot_type: str | None = pa.Field(nullable=True)
    shot_clock_range: str | None = pa.Field(nullable=True)
    touch_time_range: str | None = pa.Field(nullable=True)
    fga_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg2a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    defense_category: str | None = pa.Field(nullable=True)
    freq: float | None = pa.Field(nullable=True, ge=0.0)
    d_fgm: int | None = pa.Field(nullable=True, ge=0)
    d_fga: int | None = pa.Field(nullable=True, ge=0)
    d_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    normal_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    pct_plusminus: float | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)
    tracking_type: str = pa.Field(
        nullable=False,
        isin=["pass", "pass_received", "rebound", "shots", "shot_defend"],
    )


class FactPlayerPtPassSchema(StagingPlayerPtPassSchema):
    pass


class FactPlayerPtShotDefendSchema(StagingPlayerPtShotDefendSchema):
    pass


class FactPlayerPtRebDetailSchema(_PlayerPtRebSchema):
    breakdown_type: str = pa.Field(
        nullable=False,
        isin=["base", "overall", "distance", "shot_dist", "shot_type"],
    )


class FactPlayerPtShotsDetailSchema(_PlayerPtShotsSchema):
    breakdown_type: str = pa.Field(
        nullable=False,
        isin=["base", "closest_def", "dribble", "general", "overall", "shot_clock", "touch_time"],
    )


class FactPlayerShootingSplitsDetailSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_value: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pct_ast_2pm: float | None = pa.Field(nullable=True)
    pct_uast_2pm: float | None = pa.Field(nullable=True)
    pct_ast_3pm: float | None = pa.Field(nullable=True)
    pct_uast_3pm: float | None = pa.Field(nullable=True)
    pct_ast_fgm: float | None = pa.Field(nullable=True)
    pct_uast_fgm: float | None = pa.Field(nullable=True)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    efg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_2pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_2pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_3pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_3pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)
    shooting_split: str = pa.Field(
        nullable=False,
        isin=[
            "assisted_by",
            "assisted_shot",
            "overall",
            "by_5ft",
            "by_8ft",
            "by_area",
            "by_type",
            "type_summary",
        ],
    )


class FactPlayerGameLogSchema(_PlayerGameLogsSchema):
    pass


class FactPlayerNextGamesSchema(StagingPlayerNextGamesSchema):
    pass


class FactPlayerProfileSchema(BaseSchema):
    player_id: int | None = pa.Field(nullable=True, gt=0)
    game_id: str | None = pa.Field(nullable=True)
    game_date: str | None = pa.Field(nullable=True)
    game_time: str | None = pa.Field(nullable=True)
    location: str | None = pa.Field(nullable=True)
    vs_team_id: int | None = pa.Field(nullable=True, gt=0)
    vs_team_city: str | None = pa.Field(nullable=True)
    vs_team_name: str | None = pa.Field(nullable=True)
    vs_team_abbreviation: str | None = pa.Field(nullable=True)
    vs_team_nickname: str | None = pa.Field(nullable=True)
    player_team_id: int | None = pa.Field(nullable=True, gt=0)
    player_team_city: str | None = pa.Field(nullable=True)
    player_team_nickname: str | None = pa.Field(nullable=True)
    player_team_abbreviation: str | None = pa.Field(nullable=True)
    stat: str | None = pa.Field(nullable=True)
    stat_value: float | None = pa.Field(nullable=True)
    stats_value: float | None = pa.Field(nullable=True)
    stat_order: int | None = pa.Field(nullable=True, ge=0)
    date_est: str | None = pa.Field(nullable=True)
    season_id: str | None = pa.Field(nullable=True)
    league_id: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    organization_id: int | None = pa.Field(nullable=True, gt=0)
    school_name: str | None = pa.Field(nullable=True)
    player_age: float | None = pa.Field(nullable=True, ge=0.0)
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
    profile_type: str = pa.Field(
        nullable=False,
        isin=[
            "career_highs",
            "season_highs",
            "next_game",
            "season_regular",
            "season_postseason",
            "season_allstar",
            "season_college",
            "season_preseason",
            "ranks_regular",
            "ranks_postseason",
            "total_regular",
            "total_postseason",
            "total_allstar",
            "total_college",
            "total_preseason",
        ],
    )


derived_output_schema(literal_fields={"career_type"})(FactPlayerCareerSchema)
derived_output_schema(literal_fields={"rank_type"})(FactPlayerSeasonRanksSchema)
derived_output_schema(literal_fields={"rollup_type"})(FactCollegeRollupSchema)
derived_output_schema(literal_fields={"matchup_type"})(FactPlayerMatchupsSchema)
derived_output_schema(literal_fields={"tracking_type"})(FactPlayerPtTrackingSchema)
derived_output_schema()(FactPlayerPtPassSchema)
derived_output_schema()(FactPlayerPtShotDefendSchema)
derived_output_schema(literal_fields={"breakdown_type"})(FactPlayerPtRebDetailSchema)
derived_output_schema(literal_fields={"breakdown_type"})(FactPlayerPtShotsDetailSchema)
derived_output_schema()(FactPlayerShootingSplitsDetailSchema)
derived_output_schema()(FactPlayerGameLogSchema)
derived_output_schema()(FactPlayerNextGamesSchema)
derived_output_schema(literal_fields={"profile_type"})(FactPlayerProfileSchema)
