from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema
from nbadb.schemas.staging.game_log import StagingTeamGameLogSchema
from nbadb.schemas.staging.team import StagingTeamDetailsSchema
from nbadb.schemas.star.fact_estimated_metrics import FactTeamEstimatedMetricsSchema
from nbadb.schemas.star.fact_team_dashboard import FactTeamPlayerDashboardSchema
from nbadb.schemas.star.fact_team_reference import (
    FactTeamAwardsConfSchema,
    FactTeamAwardsDivSchema,
    FactTeamHofSchema,
    FactTeamRetiredSchema,
    FactTeamSeasonRanksSchema,
    FactTeamSocialSitesSchema,
)


class StagingTeamAwardsConfSchema(FactTeamAwardsConfSchema):
    pass


class StagingTeamAwardsDivSchema(FactTeamAwardsDivSchema):
    pass


class StagingTeamAwardsChampionshipsSchema(FactTeamAwardsConfSchema):
    pass


class StagingTeamBackgroundSchema(StagingTeamDetailsSchema):
    pass


class StagingTeamHistorySchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    city: str | None = pa.Field(nullable=True)
    nickname: str | None = pa.Field(nullable=True)
    yearfounded: int | None = pa.Field(nullable=True, gt=1900)
    yearactivetill: int | None = pa.Field(nullable=True, gt=1900)


class StagingTeamHofSchema(FactTeamHofSchema):
    pass


class StagingTeamRetiredSchema(FactTeamRetiredSchema):
    pass


class StagingTeamSocialSitesSchema(FactTeamSocialSitesSchema):
    pass


class StagingTeamDashboardEstimatedSchema(FactTeamEstimatedMetricsSchema):
    team_name: str | None = pa.Field(nullable=True)
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    e_tm_tov_pct: float | None = pa.Field(nullable=True, ge=0.0)
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
    e_tm_tov_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    e_pace_rank: int | None = pa.Field(nullable=True, ge=0)


class StagingTeamGameLogsV2Schema(StagingTeamGameLogSchema):
    season_year: str = pa.Field(nullable=False)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
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


class StagingTeamHistoricalLeadersSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    pts_person_id: int | None = pa.Field(nullable=True, gt=0)
    pts_player: str | None = pa.Field(nullable=True)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    ast_person_id: int | None = pa.Field(nullable=True, gt=0)
    ast_player: str | None = pa.Field(nullable=True)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    reb_person_id: int | None = pa.Field(nullable=True, gt=0)
    reb_player: str | None = pa.Field(nullable=True)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blk_person_id: int | None = pa.Field(nullable=True, gt=0)
    blk_player: str | None = pa.Field(nullable=True)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    stl_person_id: int | None = pa.Field(nullable=True, gt=0)
    stl_player: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)


class StagingTeamAvailableSeasonsSchema(BaseSchema):
    season_id: str = pa.Field(nullable=False)


class StagingTeamSeasonRanksSchema(FactTeamSeasonRanksSchema):
    pass


class StagingTeamPlayerDashboardSchema(FactTeamPlayerDashboardSchema):
    pass


class StagingTeamPlayerDashPlayersSchema(FactTeamPlayerDashboardSchema):
    pass


class StagingTeamPlayerDashOverallSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_name: str | None = pa.Field(nullable=True)
    group_value: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
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


class _TeamOnOffSummarySchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_value: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    off_rating: float | None = pa.Field(nullable=True)
    def_rating: float | None = pa.Field(nullable=True)
    net_rating: float | None = pa.Field(nullable=True)


class _TeamOnOffDetailedSchema(_TeamOnOffSummarySchema):
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
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


class StagingTeamDashboardOnOffSchema(BaseSchema):
    group_set: str | None = pa.Field(nullable=True)
    group_value: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    season_year: str = pa.Field(nullable=False)
    season_type: str = pa.Field(nullable=False)
    on_off: str = pa.Field(nullable=False)
    gp: int | None = pa.Field(nullable=True, ge=0)
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus: float | None = pa.Field(nullable=True)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)
    off_rating: float | None = pa.Field(nullable=True)
    def_rating: float | None = pa.Field(nullable=True)
    net_rating: float | None = pa.Field(nullable=True)


class StagingOnOffSchema(StagingTeamDashboardOnOffSchema):
    player_id: int = pa.Field(gt=0, nullable=False)


class StagingOnOffDetailsOverallSchema(_TeamOnOffDetailedSchema):
    pass


class StagingOnOffDetailsOffCourtSchema(_TeamOnOffDetailedSchema):
    pass


class StagingOnOffDetailsOnCourtSchema(_TeamOnOffDetailedSchema):
    pass


class StagingOnOffSummaryOverallSchema(_TeamOnOffDetailedSchema):
    pass


class StagingOnOffSummaryOffCourtSchema(_TeamOnOffSummarySchema):
    pass


class StagingOnOffSummaryOnCourtSchema(_TeamOnOffSummarySchema):
    pass


class StagingTeamYearByYearSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    team_city: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    year: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    wins: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0)
    win_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    conf_rank: int | None = pa.Field(nullable=True, ge=0)
    div_rank: int | None = pa.Field(nullable=True, ge=0)
    po_wins: int | None = pa.Field(nullable=True, ge=0)
    po_losses: int | None = pa.Field(nullable=True, ge=0)
    conf_count: int | None = pa.Field(nullable=True, ge=0)
    div_count: int | None = pa.Field(nullable=True, ge=0)
    nba_finals_appearance: str | None = pa.Field(nullable=True)
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
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)


class StagingTeamYearByYearStatsSchema(StagingTeamYearByYearSchema):
    pass
