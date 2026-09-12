"""Attribute and registry tests for all stats extractor modules.

Verifies endpoint_name, category, and registry presence for every
@registry.register class across all 29 stats files.
"""

from __future__ import annotations

import json
from typing import cast

import polars as pl
import pytest

from nbadb.extract.base import BaseExtractor

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
    PlayerFantasyProfileBarGraphExtractor,
    TeamGameStreakFinderExtractor,
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
    VideoEventsExtractor,
    VideoStatusExtractor,
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
    PlayerDashPtPassExtractor,
    PlayerDashPtRebExtractor,
    PlayerDashPtShotsExtractor,
    PlayerEstimatedMetricsExtractor,
)
from nbadb.extract.stats.rotation import GameRotationExtractor

# ── schedule / rotation / synergy / win_probability ─────────────────────────
from nbadb.extract.stats.schedule import ScheduleExtractor, ScheduleIntExtractor

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
from tests.unit.extract._extractor_test_types import (
    ExtractorCls,
    RosterCoachesExtractor,
    provider_kwargs,
)

_RAW_RESPONSE_UNSET = object()

# ---------------------------------------------------------------------------
# Parametrized attribute tests
# ---------------------------------------------------------------------------

_ALL_EXTRACTORS: list[tuple[ExtractorCls, str, str]] = [
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
    # schedule (2)
    (ScheduleExtractor, "schedule", "schedule"),
    (ScheduleIntExtractor, "schedule_int", "schedule"),
    # rotation (1)
    (GameRotationExtractor, "game_rotation", "rotation"),
    # synergy (1)
    (SynergyPlayTypesExtractor, "synergy_play_types", "synergy"),
    # win_probability (1) -- category is "play_by_play"
    (WinProbabilityExtractor, "win_probability", "play_by_play"),
    # hustle (1)
    (HustleStatsBoxScoreExtractor, "hustle_stats_box_score", "hustle"),
    # tracking_defense (2)
    (LeagueDashPtDefendExtractor, "league_dash_pt_defend", "tracking"),
    (LeagueDashPtTeamDefendExtractor, "league_dash_pt_team_defend", "tracking"),
    # player_game_log (2)
    (PlayerGameLogsExtractor, "player_game_logs", "game_log"),
    (PlayerGameStreakFinderExtractor, "player_game_streak_finder", "player_info"),
    # player_tracking (4)
    (PlayerDashPtShotsExtractor, "player_dash_pt_shots", "player_info"),
    (PlayerDashPtPassExtractor, "player_dash_pt_pass", "player_info"),
    (PlayerDashPtRebExtractor, "player_dash_pt_reb", "player_info"),
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
    # misc (10)
    (CumeStatsPlayerExtractor, "cume_stats_player", "misc"),
    (CumeStatsPlayerGamesExtractor, "cume_stats_player_games", "misc"),
    (CumeStatsTeamExtractor, "cume_stats_team", "misc"),
    (CumeStatsTeamGamesExtractor, "cume_stats_team_games", "misc"),
    (LeagueGameFinderExtractor, "league_game_finder", "misc"),
    (TeamGameStreakFinderExtractor, "team_game_streak_finder", "misc"),
    (GLAlumBoxScoreSimilarityScoreExtractor, "gl_alum_box_score_similarity_score", "misc"),
    (DunkScoreLeadersExtractor, "dunk_score_leaders", "misc"),
    (GravityLeadersExtractor, "gravity_leaders", "misc"),
    (PlayerFantasyProfileBarGraphExtractor, "player_fantasy_profile", "misc"),
    (VideoDetailsExtractor, "video_details", "misc"),
    (VideoDetailsAssetExtractor, "video_details_asset", "misc"),
    (VideoEventsExtractor, "video_events", "misc"),
    (VideoStatusExtractor, "video_status", "misc"),
]


@pytest.mark.parametrize(
    "cls, expected_name, expected_category",
    _ALL_EXTRACTORS,
    ids=[t[1] for t in _ALL_EXTRACTORS],
)
class TestExtractorAttributes:
    def test_endpoint_name(
        self, cls: ExtractorCls, expected_name: str, expected_category: str
    ) -> None:
        assert cls.endpoint_name == expected_name

    def test_category(self, cls: ExtractorCls, expected_name: str, expected_category: str) -> None:
        assert cls.category == expected_category

    def test_is_subclass_of_base(
        self,
        cls: ExtractorCls,
        expected_name: str,
        expected_category: str,
    ) -> None:
        assert issubclass(cls, BaseExtractor)

    def test_has_extract_method(
        self,
        cls: ExtractorCls,
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


class TestCrossProductParameterHandling:
    @staticmethod
    def _common_team_roster_df() -> pl.DataFrame:
        return pl.DataFrame(
            {
                "team_id": [1610612738],
                "season": ["2024-25"],
                "league_id": ["00"],
                "player": ["Roster Player"],
                "nickname": ["Roster"],
                "player_slug": ["roster-player"],
                "num": ["0"],
                "position": ["G"],
                "height": ["6-0"],
                "weight": ["180"],
                "birth_date": ["2000-01-01"],
                "age": [24.0],
                "exp": ["1"],
                "school": ["Example"],
                "player_id": [1],
                "how_acquired": ["Draft"],
            }
        )

    @staticmethod
    def _common_team_roster_coaches_df() -> pl.DataFrame:
        return pl.DataFrame(
            {
                "team_id": [1610612738],
                "season": ["2024-25"],
                "coach_id": [2],
                "first_name": ["Head"],
                "last_name": ["Coach"],
                "coach_name": ["Head Coach"],
                "is_assistant": [0],
                "coach_type": ["Head Coach"],
                "sort_sequence": [1],
                "sub_sort_sequence": [1],
                "school": ["Example"],
            }
        )

    @pytest.mark.asyncio
    async def test_common_team_roster_extract_returns_roster_result_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonTeamRosterExtractor()
        coaches = self._common_team_roster_coaches_df()
        roster = self._common_team_roster_df()
        trailing = pl.DataFrame({"unexpected": ["trailing packet"]})

        monkeypatch.setattr(
            ext, "_from_nba_api_multi", lambda endpoint_cls, **kwargs: [coaches, roster, trailing]
        )

        result = await ext.extract(team_id=1610612738, season="2024-25")

        assert result.columns == roster.columns
        assert result["player"][0] == "Roster Player"

    @pytest.mark.asyncio
    async def test_common_team_roster_extract_coaches_returns_coaches_result_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cast("RosterCoachesExtractor", CommonTeamRosterExtractor())
        coaches = self._common_team_roster_coaches_df()
        roster = self._common_team_roster_df()
        trailing = pl.DataFrame({"unexpected": ["trailing packet"]})

        monkeypatch.setattr(
            ext, "_from_nba_api_multi", lambda endpoint_cls, **kwargs: [coaches, roster, trailing]
        )

        result = await ext.extract_coaches(team_id=1610612738, season="2024-25")

        assert result.columns == coaches.columns
        assert result["coach_name"][0] == "Head Coach"

    @pytest.mark.asyncio
    async def test_player_compare_accepts_single_player_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerCompareExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(player_id=201939, season="2024-25")

        kwargs = provider_kwargs(captured)
        assert kwargs["player_id_list"] == "201939"
        assert kwargs["vs_player_id_list"] == "201939"
        assert kwargs["season"] == "2024-25"

    @pytest.mark.asyncio
    async def test_player_compare_returns_empty_when_ids_missing(self) -> None:
        ext = PlayerCompareExtractor()
        result = await ext.extract(season="2024-25")
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_gl_alum_accepts_player_season_and_defaults_to_self_compare(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = GLAlumBoxScoreSimilarityScoreExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(player_id=201939, season="2024-25")

        kwargs = provider_kwargs(captured)
        assert kwargs["person1_id"] == 201939
        assert kwargs["person2_id"] == 201939
        assert kwargs["person1_season_year"] == 2024
        assert kwargs["person2_season_year"] == 2024
        assert kwargs["person1_season_type"] == "Regular Season"
        assert kwargs["person2_season_type"] == "Regular Season"

    @pytest.mark.asyncio
    async def test_player_game_log_season_is_optional(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerGameLogExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(player_id=2544)

        kwargs = provider_kwargs(captured)
        assert kwargs["player_id"] == 2544
        assert "season" not in kwargs

    @pytest.mark.asyncio
    async def test_team_game_log_season_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = TeamGameLogExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(team_id=1610612744)

        kwargs = provider_kwargs(captured)
        assert kwargs["team_id"] == 1610612744
        assert "season" not in kwargs

    @pytest.mark.asyncio
    async def test_team_info_common_uses_nullable_runtime_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = TeamInfoCommonExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(team_id=1610612737, season="2024-25", season_type="Playoffs")

        kwargs = provider_kwargs(captured)
        assert kwargs["team_id"] == 1610612737
        assert kwargs["season_nullable"] == "2024-25"
        assert kwargs["season_type_nullable"] == "Playoffs"
        assert "season" not in kwargs
        assert "season_type_all_star" not in kwargs

    @pytest.mark.asyncio
    async def test_team_game_logs_forwards_team_id_nullable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = TeamGameLogsExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(team_id=1610612737, season="2024-25", season_type="Regular Season")

        kwargs = provider_kwargs(captured)
        assert kwargs["team_id_nullable"] == 1610612737
        assert kwargs["season_nullable"] == "2024-25"
        assert kwargs["season_type_nullable"] == "Regular Season"

    @pytest.mark.asyncio
    async def test_league_game_log_forwards_timeout_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = LeagueGameLogExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", season_type="Playoffs", timeout=(3.05, 10.0))

        kwargs = provider_kwargs(captured)
        assert kwargs["timeout"] == (3.05, 10.0)

    @pytest.mark.asyncio
    async def test_player_index_season_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayerIndexExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract()

        kwargs = provider_kwargs(captured)
        assert "season" not in kwargs

    @pytest.mark.asyncio
    async def test_player_index_forwards_timeout_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerIndexExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", timeout=(3.05, 10.0))

        kwargs = provider_kwargs(captured)
        assert kwargs["timeout"] == (3.05, 10.0)

    @pytest.mark.asyncio
    async def test_common_all_players_omits_empty_season_param(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract()

        kwargs = provider_kwargs(captured)
        assert kwargs["is_only_current_season"] == 0
        assert "season" not in kwargs

    @pytest.mark.asyncio
    async def test_common_all_players_forwards_timeout_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured["kwargs"] = kwargs
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", timeout=(3.05, 10.0))

        kwargs = provider_kwargs(captured)
        assert kwargs["timeout"] == (3.05, 10.0)

    @pytest.mark.asyncio
    async def test_common_all_players_fails_closed_when_unscoped_json_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise json.JSONDecodeError("bad json", "", 0)

        monkeypatch.setattr(ext, "_from_nba_api", _boom)
        with pytest.raises(json.JSONDecodeError, match="bad json"):
            await ext.extract()

    @pytest.mark.asyncio
    async def test_common_all_players_rejects_explicit_static_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        with pytest.raises(ValueError, match="static_players extractor explicitly"):
            await ext.extract(is_only_current_season=1, allow_static_fallback=True)

    @pytest.mark.asyncio
    async def test_common_all_players_propagates_retryable_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise ConnectionError("transient failure")

        monkeypatch.setattr(ext, "_from_nba_api", _boom)
        with pytest.raises(ConnectionError, match="transient failure"):
            await ext.extract()

    @pytest.mark.asyncio
    async def test_common_all_players_can_disable_static_fallback_after_retryable_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise ConnectionError("transient failure")

        monkeypatch.setattr(ext, "_from_nba_api", _boom)

        with pytest.raises(ConnectionError, match="transient failure"):
            await ext.extract(allow_static_fallback=False)

    @pytest.mark.asyncio
    async def test_common_all_players_re_raises_json_error_for_season_scoped_requests(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise json.JSONDecodeError("bad json", "", 0)

        monkeypatch.setattr(ext, "_from_nba_api", _boom)

        with pytest.raises(json.JSONDecodeError, match="bad json"):
            await ext.extract(season="2024-25")

    @pytest.mark.asyncio
    async def test_common_all_players_re_raises_structural_error_for_unscoped_requests(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = CommonAllPlayersExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise KeyError("resultSet")

        monkeypatch.setattr(ext, "_from_nba_api", _boom)

        with pytest.raises(KeyError, match="resultSet"):
            await ext.extract()
