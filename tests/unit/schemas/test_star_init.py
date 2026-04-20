"""Smoke test: every __all__ entry in nbadb.schemas.star is importable."""

import nbadb.schemas.star as pkg

_EXPECTED_ANALYTICS_EXPORTS = {
    "AnalyticsClutchPerformanceSchema",
    "AnalyticsDraftValueSchema",
    "AnalyticsGameSummarySchema",
    "AnalyticsHeadToHeadSchema",
    "AnalyticsLeagueBenchmarksSchema",
    "AnalyticsPlayerGameCompleteSchema",
    "AnalyticsPlayerImpactSchema",
    "AnalyticsPlayerMatchupSchema",
    "AnalyticsPlayerSeasonCompleteSchema",
    "AnalyticsShootingEfficiencySchema",
    "AnalyticsTeamGameCompleteSchema",
    "AnalyticsTeamSeasonSummarySchema",
}

_EXPECTED_FACT_EXPORTS = {
    "FactPlayerEstimatedMetricsSchema",
    "FactTeamEstimatedMetricsSchema",
}


def test_star_init_all_exports():
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"{name} in __all__ but not importable"


def test_star_init_exports_expected_analytics_schemas():
    assert _EXPECTED_ANALYTICS_EXPORTS.issubset(pkg.__all__)


def test_star_init_exports_expected_fact_schemas():
    assert _EXPECTED_FACT_EXPORTS.issubset(pkg.__all__)
