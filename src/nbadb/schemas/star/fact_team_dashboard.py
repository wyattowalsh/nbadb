from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class _TeamDashboardSeasonTypeMixin(BaseSchema):
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )


class _TeamDashboardGroupSetMixin(BaseSchema):
    group_set: str = pa.Field(metadata={"description": "Dashboard grouping set"})


class _TeamDashboardGroupingMixin(_TeamDashboardGroupSetMixin):
    group_value: str | None = pa.Field(
        nullable=True, metadata={"description": "Dashboard grouping value"}
    )


class _TeamDashboardPlayerIdentityMixin(BaseSchema):
    player_id: int = pa.Field(gt=0, metadata={"description": "Player identifier"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )


class _TeamDashboardReferenceMixin(BaseSchema):
    cfid: int | None = pa.Field(nullable=True, ge=0)
    cfparams: str | None = pa.Field(nullable=True)


class _TeamDashboardFieldGoalMetricsMixin(BaseSchema):
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)


class _TeamDashboardFieldGoalRanksMixin(BaseSchema):
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)


class _TeamDashboardStandardMetricsMixin(_TeamDashboardFieldGoalMetricsMixin):
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)


class _TeamDashboardStandardRanksMixin(_TeamDashboardFieldGoalRanksMixin):
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
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
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)


class _TeamDashboardShootingExtensionsMixin(BaseSchema):
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    pct_ast_2pm: float | None = pa.Field(nullable=True, ge=0.0)
    pct_uast_2pm: float | None = pa.Field(nullable=True, ge=0.0)
    pct_ast_3pm: float | None = pa.Field(nullable=True, ge=0.0)
    pct_uast_3pm: float | None = pa.Field(nullable=True, ge=0.0)
    pct_ast_fgm: float | None = pa.Field(nullable=True, ge=0.0)
    pct_uast_fgm: float | None = pa.Field(nullable=True, ge=0.0)


class _TeamDashboardShootingExtensionRanksMixin(BaseSchema):
    efg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_2pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_2pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_3pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_3pm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_ast_fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    pct_uast_fgm_rank: int | None = pa.Field(nullable=True, ge=0)


class _TeamDashboardFantasyMetricsMixin(BaseSchema):
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    dd2: float | None = pa.Field(nullable=True, ge=0.0)
    td3: float | None = pa.Field(nullable=True, ge=0.0)


class _TeamDashboardFantasyRanksMixin(BaseSchema):
    nba_fantasy_pts_rank: int | None = pa.Field(nullable=True, ge=0)
    dd2_rank: int | None = pa.Field(nullable=True, ge=0)
    td3_rank: int | None = pa.Field(nullable=True, ge=0)


class FactTeamDashboardGeneralOverallSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})


class FactTeamDashboardShootingOverallSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class FactTeamPlayerDashboardSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupSetMixin,
    _TeamDashboardPlayerIdentityMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardFantasyMetricsMixin,
    _TeamDashboardFantasyRanksMixin,
    BaseSchema,
):
    pass


class FactTeamSplitsSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    split_type: str = pa.Field(
        isin=["general", "shooting"],
        metadata={"description": "Dashboard split family (general or shooting)"},
    )
