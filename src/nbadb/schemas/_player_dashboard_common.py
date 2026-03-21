from __future__ import annotations

from typing import Any

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


def _field(description: str, **kwargs: Any) -> Any:
    return pa.Field(metadata={"description": description}, **kwargs)


class _PlayerDashboardContextMixin(BaseSchema):
    player_id: int = _field("Queried player identifier.", nullable=False, gt=0)
    season_year: str = _field("Queried season year.", nullable=False)
    season_type: str = _field("Queried season type.", nullable=False)


class _PlayerDashboardGroupSetMixin(BaseSchema):
    group_set: str | None = _field(
        "Grouping set returned by the player dashboard endpoint.",
        nullable=True,
    )


class _PlayerDashboardGroupingMixin(_PlayerDashboardGroupSetMixin):
    group_value: str | None = _field(
        "Grouping value returned by the player dashboard endpoint.",
        nullable=True,
    )


class _PlayerDashboardDetailGroupingMixin(BaseSchema):
    group_value_order: int | None = _field(
        "Sort order for grouped dashboard rows.",
        nullable=True,
        ge=0,
    )
    group_value_2: str | None = _field(
        "Secondary grouping value returned by the endpoint.",
        nullable=True,
    )


class _PlayerDashboardReferenceMixin(BaseSchema):
    cfid: int | None = _field(
        "Context filter identifier returned by nba_api.",
        nullable=True,
        ge=0,
    )
    cfparams: str | None = _field(
        "Serialized context filter parameters returned by nba_api.",
        nullable=True,
    )


class _PlayerDashboardFieldGoalMetricsMixin(BaseSchema):
    fgm: float | None = _field("Field goals made.", nullable=True, ge=0)
    fga: float | None = _field("Field goals attempted.", nullable=True, ge=0)
    fg_pct: float | None = _field(
        "Field goal percentage.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    fg3m: float | None = _field("Three-pointers made.", nullable=True, ge=0)
    fg3a: float | None = _field("Three-pointers attempted.", nullable=True, ge=0)
    fg3_pct: float | None = _field(
        "Three-point percentage.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    blka: float | None = _field("Blocked attempts.", nullable=True, ge=0)


class _PlayerDashboardFieldGoalRanksMixin(BaseSchema):
    fgm_rank: int | None = _field("Field goals made rank.", nullable=True, ge=0)
    fga_rank: int | None = _field("Field goals attempted rank.", nullable=True, ge=0)
    fg_pct_rank: int | None = _field("Field goal percentage rank.", nullable=True, ge=0)
    fg3m_rank: int | None = _field("Three-pointers made rank.", nullable=True, ge=0)
    fg3a_rank: int | None = _field("Three-pointers attempted rank.", nullable=True, ge=0)
    fg3_pct_rank: int | None = _field("Three-point percentage rank.", nullable=True, ge=0)
    blka_rank: int | None = _field("Blocked attempts rank.", nullable=True, ge=0)


class _PlayerDashboardStandardMetricsMixin(_PlayerDashboardFieldGoalMetricsMixin):
    gp: int | None = _field("Games played.", nullable=True, ge=0)
    w: int | None = _field("Wins.", nullable=True, ge=0)
    l: int | None = _field("Losses.", nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = _field(
        "Win percentage.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    min: float | None = _field("Minutes played.", nullable=True, ge=0)
    ftm: float | None = _field("Free throws made.", nullable=True, ge=0)
    fta: float | None = _field("Free throws attempted.", nullable=True, ge=0)
    ft_pct: float | None = _field(
        "Free throw percentage.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    oreb: float | None = _field("Offensive rebounds.", nullable=True, ge=0)
    dreb: float | None = _field("Defensive rebounds.", nullable=True, ge=0)
    reb: float | None = _field("Total rebounds.", nullable=True, ge=0)
    ast: float | None = _field("Assists.", nullable=True, ge=0)
    tov: float | None = _field("Turnovers.", nullable=True, ge=0)
    stl: float | None = _field("Steals.", nullable=True, ge=0)
    blk: float | None = _field("Blocks.", nullable=True, ge=0)
    pf: float | None = _field("Personal fouls.", nullable=True, ge=0)
    pfd: float | None = _field("Personal fouls drawn.", nullable=True, ge=0)
    pts: float | None = _field("Points scored.", nullable=True, ge=0)
    plus_minus: float | None = _field("Plus-minus differential.", nullable=True)
    nba_fantasy_pts: float | None = _field(
        "NBA fantasy points.",
        nullable=True,
        ge=0,
    )
    dd2: float | None = _field("Double-doubles.", nullable=True, ge=0)
    td3: float | None = _field("Triple-doubles.", nullable=True, ge=0)


class _PlayerDashboardStandardRanksMixin(_PlayerDashboardFieldGoalRanksMixin):
    gp_rank: int | None = _field("Games played rank.", nullable=True, ge=0)
    w_rank: int | None = _field("Wins rank.", nullable=True, ge=0)
    l_rank: int | None = _field("Losses rank.", nullable=True, ge=0)  # noqa: E741
    w_pct_rank: int | None = _field("Win percentage rank.", nullable=True, ge=0)
    min_rank: int | None = _field("Minutes played rank.", nullable=True, ge=0)
    ftm_rank: int | None = _field("Free throws made rank.", nullable=True, ge=0)
    fta_rank: int | None = _field("Free throws attempted rank.", nullable=True, ge=0)
    ft_pct_rank: int | None = _field("Free throw percentage rank.", nullable=True, ge=0)
    oreb_rank: int | None = _field("Offensive rebounds rank.", nullable=True, ge=0)
    dreb_rank: int | None = _field("Defensive rebounds rank.", nullable=True, ge=0)
    reb_rank: int | None = _field("Rebounds rank.", nullable=True, ge=0)
    ast_rank: int | None = _field("Assists rank.", nullable=True, ge=0)
    tov_rank: int | None = _field("Turnovers rank.", nullable=True, ge=0)
    stl_rank: int | None = _field("Steals rank.", nullable=True, ge=0)
    blk_rank: int | None = _field("Blocks rank.", nullable=True, ge=0)
    pf_rank: int | None = _field("Personal fouls rank.", nullable=True, ge=0)
    pfd_rank: int | None = _field("Personal fouls drawn rank.", nullable=True, ge=0)
    pts_rank: int | None = _field("Points rank.", nullable=True, ge=0)
    plus_minus_rank: int | None = _field("Plus-minus rank.", nullable=True, ge=0)
    nba_fantasy_pts_rank: int | None = _field(
        "NBA fantasy points rank.",
        nullable=True,
        ge=0,
    )
    dd2_rank: int | None = _field("Double-doubles rank.", nullable=True, ge=0)
    td3_rank: int | None = _field("Triple-doubles rank.", nullable=True, ge=0)


class _PlayerDashboardShootingExtensionsMixin(BaseSchema):
    efg_pct: float | None = _field(
        "Effective field goal percentage.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_ast_2pm: float | None = _field(
        "Share of made twos that were assisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_uast_2pm: float | None = _field(
        "Share of made twos that were unassisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_ast_3pm: float | None = _field(
        "Share of made threes that were assisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_uast_3pm: float | None = _field(
        "Share of made threes that were unassisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_ast_fgm: float | None = _field(
        "Share of made field goals that were assisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )
    pct_uast_fgm: float | None = _field(
        "Share of made field goals that were unassisted.",
        nullable=True,
        ge=0.0,
        le=1.0,
    )


class _PlayerDashboardShootingExtensionRanksMixin(BaseSchema):
    efg_pct_rank: int | None = _field(
        "Effective field goal percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_ast_2pm_rank: int | None = _field(
        "Assisted two-point make percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_uast_2pm_rank: int | None = _field(
        "Unassisted two-point make percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_ast_3pm_rank: int | None = _field(
        "Assisted three-point make percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_uast_3pm_rank: int | None = _field(
        "Unassisted three-point make percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_ast_fgm_rank: int | None = _field(
        "Assisted field goal make percentage rank.",
        nullable=True,
        ge=0,
    )
    pct_uast_fgm_rank: int | None = _field(
        "Unassisted field goal make percentage rank.",
        nullable=True,
        ge=0,
    )


class _PlayerDashboardYearOverYearContextMixin(BaseSchema):
    team_id: int | None = _field("Team identifier for the season row.", nullable=True, gt=0)
    team_abbreviation: str | None = _field("Team abbreviation.", nullable=True)
    max_game_date: str | None = _field("Most recent game date in the split.", nullable=True)


class _PlayerDashboardAssistedByIdentityMixin(BaseSchema):
    player_name: str | None = _field(
        "Player name returned by the assisted-by split.", nullable=True
    )


class _PlayerDashboardSplitTypeMixin(BaseSchema):
    split_type: str = _field("Dashboard family represented by the union row.", nullable=False)


__all__ = [
    "_PlayerDashboardAssistedByIdentityMixin",
    "_PlayerDashboardContextMixin",
    "_PlayerDashboardDetailGroupingMixin",
    "_PlayerDashboardFieldGoalMetricsMixin",
    "_PlayerDashboardFieldGoalRanksMixin",
    "_PlayerDashboardGroupSetMixin",
    "_PlayerDashboardGroupingMixin",
    "_PlayerDashboardReferenceMixin",
    "_PlayerDashboardShootingExtensionRanksMixin",
    "_PlayerDashboardShootingExtensionsMixin",
    "_PlayerDashboardSplitTypeMixin",
    "_PlayerDashboardStandardMetricsMixin",
    "_PlayerDashboardStandardRanksMixin",
    "_PlayerDashboardYearOverYearContextMixin",
]
