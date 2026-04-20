from __future__ import annotations

from nbadb.schemas._player_dashboard_common import (
    _PlayerDashboardAssistedByIdentityMixin,
    _PlayerDashboardContextMixin,
    _PlayerDashboardDetailGroupingMixin,
    _PlayerDashboardFieldGoalMetricsMixin,
    _PlayerDashboardFieldGoalRanksMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardGroupSetMixin,
    _PlayerDashboardReferenceMixin,
    _PlayerDashboardShootingExtensionRanksMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardYearOverYearContextMixin,
)
from nbadb.schemas.base import BaseSchema


class StagingPlayerDashboardClutchSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardGameSplitsSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardGeneralSplitsSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardLastNGamesSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardShootingSplitsSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardFieldGoalMetricsMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardFieldGoalRanksMixin,
    _PlayerDashboardShootingExtensionRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardTeamPerformanceSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerDashboardYearOverYearSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardYearOverYearContextMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerShootAssistedBySchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupSetMixin,
    _PlayerDashboardAssistedByIdentityMixin,
    _PlayerDashboardFieldGoalMetricsMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardFieldGoalRanksMixin,
    _PlayerDashboardShootingExtensionRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerShootTypeSummarySchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardFieldGoalMetricsMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerPerfPtsScoredSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardDetailGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass
