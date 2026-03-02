"""Attribute and registry tests for all stats extractor modules.

Verifies endpoint_name, category, and registry presence for every
@registry.register class across all 29 stats files.
"""

from __future__ import annotations

import pytest

# ── all_time ────────────────────────────────────────────────────────────────
from nbadb.extract.stats.all_time import AllTimeLeadersGridsExtractor

# ── box_scores ──────────────────────────────────────────────────────────────
from nbadb.extract.stats.box_scores import (
    BoxScoreAdvancedExtractor,
    BoxScoreDefensiveExtractor,
    BoxScoreFourFactorsExtractor,
    BoxScoreHustleExtractor,
    BoxScoreMiscExtractor,
    BoxScorePlayerTrackExtractor,
    BoxScoreScoringExtractor,
    BoxScoreTraditionalExtractor,
    BoxScoreUsageExtractor,
)
from nbadb.extract.stats.box_summary import BoxScoreSummaryExtractor

# ── draft ───────────────────────────────────────────────────────────────────
from nbadb.extract.stats.draft import (
    DraftBoardExtractor,
    DraftCombineDrillResultsExtractor,
    DraftCombineNonStationaryShootingExtractor,
    DraftCombinePlayerAnthroExtractor,
    DraftCombineSpotShootingExtractor,
    DraftCombineStatsExtractor,
    DraftHistoryExtractor,
)

# ── franchise ───────────────────────────────────────────────────────────────
from nbadb.extract.stats.franchise import (
    FranchiseLeadersExtractor,
    FranchisePlayersExtractor,
)

# ── game_log ────────────────────────────────────────────────────────────────
from nbadb.extract.stats.game_log import (
    LeagueGameLogExtractor,
    PlayerGameLogExtractor,
    ScoreboardV2Extractor,
    TeamGameLogExtractor,
)

# ── hustle ──────────────────────────────────────────────────────────────────
from nbadb.extract.stats.hustle import (
    HustleStatsBoxScoreExtractor,
    LeagueHustleStatsPlayerExtractor,
    LeagueHustleStatsTeamExtractor,
)

# ── leaders ─────────────────────────────────────────────────────────────────
from nbadb.extract.stats.leaders import (
    AssistLeadersExtractor,
    AssistTrackerExtractor,
    DefenseHubExtractor,
    HomePageLeadersExtractor,
    HomePageV2Extractor,
    LeadersTilesExtractor,
    LeagueLeadersExtractor,
    TeamHistoricalLeadersExtractor,
    TeamYearByYearStatsExtractor,
)

# ── league_shot_locations ───────────────────────────────────────────────────
from nbadb.extract.stats.league_shot_locations import (
    LeagueDashOppPtShotExtractor,
    LeagueDashPlayerPtShotExtractor,
    LeagueDashPlayerShotLocationsExtractor,
    LeagueDashPtStatsExtractor,
    LeagueDashTeamPtShotExtractor,
    LeagueDashTeamShotLocationsExtractor,
    LeaguePlayerOnDetailsExtractor,
)

# ── league_stats ────────────────────────────────────────────────────────────
from nbadb.extract.stats.league_stats import (
    LeagueDashPlayerBioStatsExtractor,
    LeagueDashPlayerClutchExtractor,
    LeagueDashPlayerStatsExtractor,
    LeagueDashTeamClutchExtractor,
    LeagueDashTeamStatsExtractor,
)

# ── matchups ────────────────────────────────────────────────────────────────
from nbadb.extract.stats.matchups import (
    BoxScoreMatchupsExtractor,
    LeagueDashLineupsExtractor,
    LeagueSeasonMatchupsExtractor,
    MatchupsRollupExtractor,
    TeamDashLineupsExtractor,
)

# ── misc ────────────────────────────────────────────────────────────────────
from nbadb.extract.stats.misc import (
    CumeStatsPlayerExtractor,
    CumeStatsPlayerGamesExtractor,
    CumeStatsTeamExtractor,
    CumeStatsTeamGamesExtractor,
    DunkScoreLeadersExtractor,
    GLAlumBoxScoreSimilarityScoreExtractor,
    GravityLeadersExtractor,
    LeagueGameFinderExtractor,
    TeamGameStreakFinderExtractor,
)

# ── play_by_play ────────────────────────────────────────────────────────────
from nbadb.extract.stats.play_by_play import (
    PlayByPlayExtractor,
    PlayByPlayV2Extractor,
)

# ── player_college ──────────────────────────────────────────────────────────
from nbadb.extract.stats.player_college import (
    PlayerCareerByCollegeExtractor,
    PlayerCareerByCollegeRollupExtractor,
)

# ── player_compare ──────────────────────────────────────────────────────────
from nbadb.extract.stats.player_compare import (
    PlayerCompareExtractor,
    PlayerVsPlayerExtractor,
    TeamAndPlayersVsPlayersExtractor,
    TeamVsPlayerExtractor,
)

# ── player_dashboard ────────────────────────────────────────────────────────
from nbadb.extract.stats.player_dashboard import (
    PlayerDashboardByClutchExtractor,
    PlayerDashboardByGameSplitsExtractor,
    PlayerDashboardByLastNGamesExtractor,
    PlayerDashboardByShootingSplitsExtractor,
    PlayerDashboardByTeamPerformanceExtractor,
    PlayerDashboardByYearOverYearExtractor,
    PlayerDashboardGeneralSplitsExtractor,
)

# ── player_game_log ─────────────────────────────────────────────────────────
from nbadb.extract.stats.player_game_log import (
    PlayerGameLogsExtractor,
    PlayerGameStreakFinderExtractor,
)

# ── player_info ─────────────────────────────────────────────────────────────
from nbadb.extract.stats.player_info import (
    CommonAllPlayersExtractor,
    CommonPlayerInfoExtractor,
    PlayerAwardsExtractor,
    PlayerCareerStatsExtractor,
    PlayerIndexExtractor,
    PlayerProfileV2Extractor,
)

# ── player_tracking ─────────────────────────────────────────────────────────
from nbadb.extract.stats.player_tracking import (
    PlayerDashPtDefendExtractor,
    PlayerDashPtPassExtractor,
    PlayerDashPtRebExtractor,
    PlayerDashPtShotsExtractor,
    PlayerEstimatedMetricsExtractor,
)
from nbadb.extract.stats.rotation import GameRotationExtractor

# ── schedule / rotation / synergy / win_probability ─────────────────────────
from nbadb.extract.stats.schedule import ScheduleExtractor

# ── shots ───────────────────────────────────────────────────────────────────
from nbadb.extract.stats.shots import (
    ShotChartDetailExtractor,
    ShotChartLeagueWideExtractor,
    ShotChartLineupDetailExtractor,
)

# ── standings ───────────────────────────────────────────────────────────────
from nbadb.extract.stats.standings import (
    CommonPlayoffSeriesExtractor,
    ISTStandingsExtractor,
    LeagueStandingsExtractor,
    PlayoffPictureExtractor,
)
from nbadb.extract.stats.synergy import SynergyPlayTypesExtractor

# ── team_dashboard ──────────────────────────────────────────────────────────
from nbadb.extract.stats.team_dashboard import (
    TeamDashboardByGeneralSplitsExtractor,
    TeamDashboardByShootingSplitsExtractor,
    TeamEstimatedMetricsExtractor,
    TeamPlayerDashboardExtractor,
    TeamPlayerOnOffDetailsExtractor,
    TeamPlayerOnOffSummaryExtractor,
)

# ── team_info ───────────────────────────────────────────────────────────────
from nbadb.extract.stats.team_info import (
    CommonTeamRosterExtractor,
    CommonTeamYearsExtractor,
    FranchiseHistoryExtractor,
    TeamDetailsExtractor,
    TeamGameLogsExtractor,
    TeamInfoCommonExtractor,
)

# ── team_tracking ───────────────────────────────────────────────────────────
from nbadb.extract.stats.team_tracking import (
    TeamDashPtPassExtractor,
    TeamDashPtRebExtractor,
    TeamDashPtShotsExtractor,
)

# ── tracking_defense ────────────────────────────────────────────────────────
from nbadb.extract.stats.tracking_defense import (
    LeagueDashPtDefendExtractor,
    LeagueDashPtTeamDefendExtractor,
)
from nbadb.extract.stats.win_probability import WinProbabilityExtractor

# ---------------------------------------------------------------------------
# Parametrized attribute tests
# ---------------------------------------------------------------------------

_ALL_EXTRACTORS = [
    # box_scores (9)
    (BoxScoreTraditionalExtractor, "box_score_traditional", "box_score"),
    (BoxScoreAdvancedExtractor, "box_score_advanced", "box_score"),
    (BoxScoreMiscExtractor, "box_score_misc", "box_score"),
    (BoxScoreScoringExtractor, "box_score_scoring", "box_score"),
    (BoxScoreUsageExtractor, "box_score_usage", "box_score"),
    (BoxScoreFourFactorsExtractor, "box_score_four_factors", "box_score"),
    (BoxScoreHustleExtractor, "box_score_hustle", "box_score"),
    (BoxScorePlayerTrackExtractor, "box_score_player_track", "box_score"),
    (BoxScoreDefensiveExtractor, "box_score_defensive", "box_score"),
    # box_summary (1)
    (BoxScoreSummaryExtractor, "box_score_summary", "box_score"),
    # play_by_play (2)
    (PlayByPlayExtractor, "play_by_play", "play_by_play"),
    (PlayByPlayV2Extractor, "play_by_play_v2", "play_by_play"),
    # game_log (4 + 1 from team_info + 1 from player_game_log)
    (LeagueGameLogExtractor, "league_game_log", "game_log"),
    (PlayerGameLogExtractor, "player_game_log", "game_log"),
    (TeamGameLogExtractor, "team_game_log", "game_log"),
    (ScoreboardV2Extractor, "scoreboard_v2", "game_log"),
    # player_info (6)
    (CommonPlayerInfoExtractor, "common_player_info", "player_info"),
    (PlayerCareerStatsExtractor, "player_career_stats", "player_info"),
    (PlayerAwardsExtractor, "player_awards", "player_info"),
    (PlayerIndexExtractor, "player_index", "player_info"),
    (CommonAllPlayersExtractor, "common_all_players", "player_info"),
    (PlayerProfileV2Extractor, "player_profile_v2", "player_info"),
    # team_info (5 + TeamGameLogs is game_log)
    (CommonTeamRosterExtractor, "common_team_roster", "team_info"),
    (FranchiseHistoryExtractor, "franchise_history", "team_info"),
    (TeamDetailsExtractor, "team_details", "team_info"),
    (TeamInfoCommonExtractor, "team_info_common", "team_info"),
    (CommonTeamYearsExtractor, "common_team_years", "team_info"),
    (TeamGameLogsExtractor, "team_game_logs", "game_log"),
    # draft (7)
    (DraftHistoryExtractor, "draft_history", "draft"),
    (DraftCombineStatsExtractor, "draft_combine_stats", "draft"),
    (DraftBoardExtractor, "draft_board", "draft"),
    (DraftCombineDrillResultsExtractor, "draft_combine_drill_results", "draft"),
    (DraftCombineNonStationaryShootingExtractor, "draft_combine_non_stationary_shooting", "draft"),
    (DraftCombinePlayerAnthroExtractor, "draft_combine_player_anthro", "draft"),
    (DraftCombineSpotShootingExtractor, "draft_combine_spot_shooting", "draft"),
    # standings (4)
    (LeagueStandingsExtractor, "league_standings", "standings"),
    (PlayoffPictureExtractor, "playoff_picture", "standings"),
    (CommonPlayoffSeriesExtractor, "common_playoff_series", "standings"),
    (ISTStandingsExtractor, "ist_standings", "standings"),
    # shots (3)
    (ShotChartDetailExtractor, "shot_chart_detail", "shots"),
    (ShotChartLineupDetailExtractor, "shot_chart_lineup_detail", "shots"),
    (ShotChartLeagueWideExtractor, "shot_chart_league_wide", "shots"),
    # matchups (5)
    (BoxScoreMatchupsExtractor, "box_score_matchups", "box_score"),
    (LeagueSeasonMatchupsExtractor, "league_season_matchups", "league"),
    (MatchupsRollupExtractor, "matchups_rollup", "league"),
    (LeagueDashLineupsExtractor, "league_dash_lineups", "league"),
    (TeamDashLineupsExtractor, "team_dash_lineups", "league"),
    # schedule (1)
    (ScheduleExtractor, "schedule", "schedule"),
    # rotation (1)
    (GameRotationExtractor, "game_rotation", "rotation"),
    # synergy (1)
    (SynergyPlayTypesExtractor, "synergy_play_types", "synergy"),
    # win_probability (1) -- category is "play_by_play"
    (WinProbabilityExtractor, "win_probability", "play_by_play"),
    # hustle (3)
    (LeagueHustleStatsPlayerExtractor, "league_hustle_stats_player", "hustle"),
    (LeagueHustleStatsTeamExtractor, "league_hustle_stats_team", "hustle"),
    (HustleStatsBoxScoreExtractor, "hustle_stats_box_score", "hustle"),
    # tracking_defense (2)
    (LeagueDashPtDefendExtractor, "league_dash_pt_defend", "tracking"),
    (LeagueDashPtTeamDefendExtractor, "league_dash_pt_team_defend", "tracking"),
    # player_game_log (2)
    (PlayerGameLogsExtractor, "player_game_logs", "game_log"),
    (PlayerGameStreakFinderExtractor, "player_game_streak_finder", "player_info"),
    # player_tracking (5)
    (PlayerDashPtShotsExtractor, "player_dash_pt_shots", "player_info"),
    (PlayerDashPtPassExtractor, "player_dash_pt_pass", "player_info"),
    (PlayerDashPtRebExtractor, "player_dash_pt_reb", "player_info"),
    (PlayerDashPtDefendExtractor, "player_dash_pt_defend", "player_info"),
    (PlayerEstimatedMetricsExtractor, "player_estimated_metrics", "player_info"),
    # player_college (2)
    (PlayerCareerByCollegeExtractor, "player_career_by_college", "player_info"),
    (PlayerCareerByCollegeRollupExtractor, "player_career_by_college_rollup", "player_info"),
    # player_dashboard (7)
    (PlayerDashboardByYearOverYearExtractor, "player_dashboard_year_over_year", "player_info"),
    (PlayerDashboardByLastNGamesExtractor, "player_dashboard_last_n_games", "player_info"),
    (PlayerDashboardByGameSplitsExtractor, "player_dashboard_game_splits", "player_info"),
    (PlayerDashboardByClutchExtractor, "player_dashboard_clutch", "player_info"),
    (PlayerDashboardByShootingSplitsExtractor, "player_dashboard_shooting_splits", "player_info"),
    (PlayerDashboardByTeamPerformanceExtractor, "player_dashboard_team_performance", "player_info"),
    (PlayerDashboardGeneralSplitsExtractor, "player_dashboard_general_splits", "player_info"),
    # team_dashboard (6)
    (TeamDashboardByShootingSplitsExtractor, "team_dashboard_shooting_splits", "team_info"),
    (TeamDashboardByGeneralSplitsExtractor, "team_dashboard_general_splits", "team_info"),
    (TeamPlayerOnOffDetailsExtractor, "team_player_on_off_details", "team_info"),
    (TeamPlayerOnOffSummaryExtractor, "team_player_on_off_summary", "team_info"),
    (TeamPlayerDashboardExtractor, "team_player_dashboard", "team_info"),
    (TeamEstimatedMetricsExtractor, "team_estimated_metrics", "team_info"),
    # player_compare (4)
    (PlayerCompareExtractor, "player_compare", "player_info"),
    (PlayerVsPlayerExtractor, "player_vs_player", "player_info"),
    (TeamVsPlayerExtractor, "team_vs_player", "player_info"),
    (TeamAndPlayersVsPlayersExtractor, "team_and_players_vs_players", "player_info"),
    # team_tracking (3)
    (TeamDashPtShotsExtractor, "team_dash_pt_shots", "team_info"),
    (TeamDashPtPassExtractor, "team_dash_pt_pass", "team_info"),
    (TeamDashPtRebExtractor, "team_dash_pt_reb", "team_info"),
    # league_stats (5)
    (LeagueDashPlayerStatsExtractor, "league_dash_player_stats", "league"),
    (LeagueDashTeamStatsExtractor, "league_dash_team_stats", "league"),
    (LeagueDashPlayerClutchExtractor, "league_dash_player_clutch", "league"),
    (LeagueDashTeamClutchExtractor, "league_dash_team_clutch", "league"),
    (LeagueDashPlayerBioStatsExtractor, "league_dash_player_bio_stats", "league"),
    # league_shot_locations (7)
    (LeagueDashPlayerShotLocationsExtractor, "league_dash_player_shot_locations", "league"),
    (LeagueDashTeamShotLocationsExtractor, "league_dash_team_shot_locations", "league"),
    (LeagueDashPlayerPtShotExtractor, "league_dash_player_pt_shot", "league"),
    (LeagueDashTeamPtShotExtractor, "league_dash_team_pt_shot", "league"),
    (LeagueDashOppPtShotExtractor, "league_dash_opp_pt_shot", "league"),
    (LeagueDashPtStatsExtractor, "league_dash_pt_stats", "league"),
    (LeaguePlayerOnDetailsExtractor, "league_player_on_details", "league"),
    # franchise (2)
    (FranchiseLeadersExtractor, "franchise_leaders", "franchise"),
    (FranchisePlayersExtractor, "franchise_players", "franchise"),
    # all_time (1)
    (AllTimeLeadersGridsExtractor, "all_time_leaders_grids", "leaders"),
    # leaders (9)
    (AssistLeadersExtractor, "assist_leaders", "leaders"),
    (AssistTrackerExtractor, "assist_tracker", "leaders"),
    (HomePageLeadersExtractor, "home_page_leaders", "leaders"),
    (HomePageV2Extractor, "home_page_v2", "leaders"),
    (LeadersTilesExtractor, "leaders_tiles", "leaders"),
    (LeagueLeadersExtractor, "league_leaders", "leaders"),
    (DefenseHubExtractor, "defense_hub", "leaders"),
    (TeamHistoricalLeadersExtractor, "team_historical_leaders", "leaders"),
    (TeamYearByYearStatsExtractor, "team_year_by_year_stats", "leaders"),
    # misc (9)
    (CumeStatsPlayerExtractor, "cume_stats_player", "misc"),
    (CumeStatsPlayerGamesExtractor, "cume_stats_player_games", "misc"),
    (CumeStatsTeamExtractor, "cume_stats_team", "misc"),
    (CumeStatsTeamGamesExtractor, "cume_stats_team_games", "misc"),
    (LeagueGameFinderExtractor, "league_game_finder", "misc"),
    (TeamGameStreakFinderExtractor, "team_game_streak_finder", "misc"),
    (GLAlumBoxScoreSimilarityScoreExtractor, "gl_alum_box_score_similarity_score", "misc"),
    (DunkScoreLeadersExtractor, "dunk_score_leaders", "misc"),
    (GravityLeadersExtractor, "gravity_leaders", "misc"),
]


@pytest.mark.parametrize(
    "cls, expected_name, expected_category",
    _ALL_EXTRACTORS,
    ids=[t[1] for t in _ALL_EXTRACTORS],
)
class TestExtractorAttributes:
    def test_endpoint_name(self, cls: type, expected_name: str, expected_category: str) -> None:
        assert cls.endpoint_name == expected_name

    def test_category(self, cls: type, expected_name: str, expected_category: str) -> None:
        assert cls.category == expected_category

    def test_is_subclass_of_base(
        self,
        cls: type,
        expected_name: str,
        expected_category: str,
    ) -> None:
        from nbadb.extract.base import BaseExtractor

        assert issubclass(cls, BaseExtractor)

    def test_has_extract_method(
        self,
        cls: type,
        expected_name: str,
        expected_category: str,
    ) -> None:
        assert hasattr(cls, "extract")
        assert callable(cls.extract)


class TestRegistryContainsAll:
    """Verify every extractor is in the global registry."""

    def test_all_extractors_registered(self) -> None:
        from nbadb.extract.registry import registry

        for cls, name, _ in _ALL_EXTRACTORS:
            assert registry.get(name) is cls, f"Registry missing or mismatched: {name}"

    def test_total_count_at_least_118(self) -> None:
        from nbadb.extract.registry import registry

        assert registry.count >= 118


class TestCategoryGroupings:
    """Verify category-based lookups return expected counts."""

    def test_box_score_category(self) -> None:
        from nbadb.extract.registry import registry

        box_score = registry.get_by_category("box_score")
        assert len(box_score) >= 11  # 9 box_scores + 1 summary + 1 matchups

    def test_league_category(self) -> None:
        from nbadb.extract.registry import registry

        league = registry.get_by_category("league")
        assert len(league) >= 16

    def test_player_info_category(self) -> None:
        from nbadb.extract.registry import registry

        player_info = registry.get_by_category("player_info")
        assert len(player_info) >= 20

    def test_team_info_category(self) -> None:
        from nbadb.extract.registry import registry

        team_info = registry.get_by_category("team_info")
        assert len(team_info) >= 14

    def test_leaders_category(self) -> None:
        from nbadb.extract.registry import registry

        leaders = registry.get_by_category("leaders")
        assert len(leaders) >= 10

    def test_misc_category(self) -> None:
        from nbadb.extract.registry import registry

        misc = registry.get_by_category("misc")
        assert len(misc) >= 9

    def test_game_log_category(self) -> None:
        from nbadb.extract.registry import registry

        game_log = registry.get_by_category("game_log")
        assert len(game_log) >= 6  # 4 game_log + TeamGameLogs + PlayerGameLogs

    def test_no_default_category_remains(self) -> None:
        from nbadb.extract.registry import registry

        defaults = registry.get_by_category("default")
        assert len(defaults) == 0, (
            f"Found {len(defaults)} extractors still using 'default' category: "
            f"{[c.endpoint_name for c in defaults]}"
        )
