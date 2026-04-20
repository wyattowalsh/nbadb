from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema
from nbadb.schemas.staging.player_team_family_support import (
    StagingLineupSchema,
    _TeamDashboardPlayerIdentityMixin,
)
from nbadb.schemas.star.fact_team_dashboard import (
    _TeamDashboardFantasyMetricsMixin,
    _TeamDashboardFantasyRanksMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
)


class StagingTeamLineupsSchema(StagingLineupSchema):
    season_type: str = pa.Field(nullable=False)


class StagingTeamLineupsOverallSchema(StagingTeamLineupsSchema):
    pass


class _TeamPtPassSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    team_name: str | None = pa.Field(nullable=True)
    pass_type: str | None = pa.Field(nullable=True)
    g: int | None = pa.Field(nullable=True, ge=0)
    pass_from: str | None = pa.Field(nullable=True)
    pass_to: str | None = pa.Field(nullable=True)
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
    season_type: str = pa.Field(nullable=False)


class StagingTeamPtPassSchema(_TeamPtPassSchema):
    pass


class StagingTeamPtPassReceivedSchema(_TeamPtPassSchema):
    pass


class _TeamPtRebSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    team_name: str | None = pa.Field(nullable=True)
    sort_order: int | None = pa.Field(nullable=True, ge=0)
    g: int | None = pa.Field(nullable=True, ge=0)
    reb_num_contesting_range: str | None = pa.Field(nullable=True)
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
    season_type: str = pa.Field(nullable=False)


class StagingTeamPtRebSchema(_TeamPtRebSchema):
    pass


class StagingTeamPtRebDistanceSchema(_TeamPtRebSchema):
    pass


class StagingTeamPtRebOverallSchema(_TeamPtRebSchema):
    pass


class StagingTeamPtRebShotDistSchema(_TeamPtRebSchema):
    pass


class StagingTeamPtRebShotTypeSchema(_TeamPtRebSchema):
    pass


class _TeamPtShotsSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    team_name: str | None = pa.Field(nullable=True)
    sort_order: int | None = pa.Field(nullable=True, ge=0)
    g: int | None = pa.Field(nullable=True, ge=0)
    close_def_dist_range: str | None = pa.Field(nullable=True)
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
    season_type: str = pa.Field(nullable=False)


class StagingTeamPtShotsSchema(_TeamPtShotsSchema):
    pass


class StagingTeamPtShotsClosestDefSchema(_TeamPtShotsSchema):
    pass


class StagingTeamPtShotsDribbleSchema(_TeamPtShotsSchema):
    pass


class StagingTeamPtShotsGeneralSchema(_TeamPtShotsSchema):
    pass


class StagingTeamPtShotsShotClockSchema(_TeamPtShotsSchema):
    pass


class StagingTeamPtShotsTouchTimeSchema(_TeamPtShotsSchema):
    pass


class _TeamMatchupContextMixin(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_value: str | None = pa.Field(nullable=True)
    title_description: str | None = pa.Field(nullable=True)
    description: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    vs_player_id: int | None = pa.Field(nullable=True, gt=0)
    vs_player_name: str | None = pa.Field(nullable=True)
    court_status: str | None = pa.Field(nullable=True)
    cfid: str | None = pa.Field(nullable=True)
    cfparams: str | None = pa.Field(nullable=True)


class _TeamComparisonStatsSchema(
    _TeamMatchupContextMixin,
    _TeamDashboardPlayerIdentityMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardFantasyMetricsMixin,
    _TeamDashboardFantasyRanksMixin,
    BaseSchema,
):
    pass


class _TeamComparisonShotSplitSchema(_TeamMatchupContextMixin, BaseSchema):
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingTeamVsPlayerSchema(_TeamComparisonStatsSchema):
    pass


class StagingTvpOnOffCourtSchema(_TeamComparisonStatsSchema):
    pass


class StagingTvpOverallSchema(_TeamComparisonStatsSchema):
    pass


class StagingTvpVsPlayerOverallSchema(_TeamComparisonStatsSchema):
    pass


class StagingTvpShotAreaOffSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTvpShotAreaOnSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTvpShotAreaOverallSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTvpShotDistOffSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTvpShotDistOnSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTvpShotDistOverallSchema(_TeamComparisonShotSplitSchema):
    pass


class StagingTeamAndPlayersVsSchema(_TeamComparisonStatsSchema):
    pass


class StagingTeamAndPlayersVsPlayersSchema(_TeamComparisonStatsSchema):
    pass


class StagingTapvpPlayersVsSchema(_TeamComparisonStatsSchema):
    pass


class StagingTapvpTeamOffSchema(_TeamComparisonStatsSchema):
    pass


class StagingTapvpTeamOnSchema(_TeamComparisonStatsSchema):
    pass


class StagingTapvpTeamVsSchema(_TeamComparisonStatsSchema):
    pass


class StagingTapvpTeamVsOffSchema(_TeamComparisonStatsSchema):
    pass
