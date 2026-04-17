from __future__ import annotations

from nbadb.schemas._player_dashboard_common import (
    _PlayerDashboardContextMixin,
    _PlayerDashboardFieldGoalMetricsMixin,
    _PlayerDashboardFieldGoalRanksMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardReferenceMixin,
    _PlayerDashboardShootingExtensionRanksMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardSplitTypeMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardYearOverYearContextMixin,
)
from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema()
class FactPlayerDashboardClutchOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema()
class FactPlayerDashboardGameSplitsOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema()
class FactPlayerDashboardGeneralSplitsOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema()
class FactPlayerDashboardLastNOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema()
class FactPlayerDashboardShootingOverallSchema(
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


@derived_output_schema()
class FactPlayerDashboardTeamPerfOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema()
class FactPlayerDashboardYoyOverallSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardYearOverYearContextMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


@derived_output_schema(literal_fields={"split_type"})
class FactPlayerSplitsSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardYearOverYearContextMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardShootingExtensionsMixin,
    _PlayerDashboardShootingExtensionRanksMixin,
    _PlayerDashboardReferenceMixin,
    _PlayerDashboardSplitTypeMixin,
    BaseSchema,
):
    pass
