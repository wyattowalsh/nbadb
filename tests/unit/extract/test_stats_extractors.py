"""Attribute and registry tests for all stats extractor modules.

Verifies endpoint_name, category, and registry presence for every
@registry.register class across all 29 stats files.
"""

from __future__ import annotations

import polars as pl
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
from nbadb.extract.stats.box_summary import BoxScoreSummaryExtractor, BoxScoreSummaryV3Extractor

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
    LeagueHustlePlayerExtractor,
    LeagueHustleTeamExtractor,
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
    PlayerDashGameSplitsExtractor,
    PlayerDashGeneralSplitsExtractor,
    PlayerDashLastNGamesExtractor,
    PlayerDashShootingSplitsExtractor,
    PlayerDashTeamPerfExtractor,
    PlayerDashYoyExtractor,
)

# ── player_game_log ─────────────────────────────────────────────────────────
from nbadb.extract.stats.player_game_log import (
    PlayerGameLogsExtractor,
    PlayerGameLogsV2Extractor,
    PlayerGameStreakFinderExtractor,
    PlayerStreakFinderExtractor,
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


class TestCrossProductParameterHandling:
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

        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
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

        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
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

        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
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

        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        assert kwargs["team_id"] == 1610612744
        assert "season" not in kwargs


# Per-endpoint param overrides — only entries that differ from the category default.
_EXTRACT_PARAMS: dict[str, dict[str, object]] = {
    # game_log: ScoreboardV2 needs game_date, not season
    "scoreboard_v2": {"game_date": "2024-10-22"},
    # player_info: some only need player_id (no season required by extract())
    "common_player_info": {"player_id": 201939},
    "player_career_stats": {"player_id": 201939},
    "player_awards": {"player_id": 201939},
    "player_profile_v2": {"player_id": 201939},
    # player_info: PlayerIndex / CommonAllPlayers use optional season
    "player_index": {"season": "2024-25"},
    "common_all_players": {"season": "2024-25"},
    # player_info: PlayerEstimatedMetrics only needs season (no player_id)
    "player_estimated_metrics": {"season": "2024-25"},
    # player_info: PlayerGameStreakFinder passes **params through
    "player_game_streak_finder": {"season": "2024-25"},
    # player_info: PlayerCareerByCollege* pass through or use optional params
    "player_career_by_college": {"season": "2024-25"},
    "player_career_by_college_rollup": {"season": "2024-25"},
    # player_compare special cases
    "player_compare": {"player_id": 201939, "season": "2024-25"},
    "player_vs_player": {
        "player_id": 201939,
        "vs_player_id": 201566,
        "season": "2024-25",
    },
    "team_vs_player": {
        "team_id": 1610612744,
        "vs_player_id": 201939,
        "season": "2024-25",
    },
    "team_and_players_vs_players": {
        "team_id": 1610612744,
        "player_id1": 201939,
        "player_id2": 201566,
        "season": "2024-25",
    },
    # leaders: TeamHistoricalLeaders needs team_id only
    "team_historical_leaders": {"team_id": 1610612744},
    # leaders: TeamYearByYearStats needs team_id (no season required)
    "team_year_by_year_stats": {"team_id": 1610612744},
    # leaders: AllTimeLeadersGrids needs no required params
    "all_time_leaders_grids": {},
    # league: TeamDashLineups needs team_id + season
    "team_dash_lineups": {"team_id": 1610612744, "season": "2024-25"},
    # league: LeaguePlayerOnDetails needs team_id + season
    "league_player_on_details": {"team_id": 1610612744, "season": "2024-25"},
    # misc: CumeStats* need player_id or team_id + season
    "cume_stats_player": {"player_id": 201939, "season": "2024-25"},
    "cume_stats_player_games": {"player_id": 201939, "season": "2024-25"},
    "cume_stats_team": {"team_id": 1610612744, "season": "2024-25"},
    "cume_stats_team_games": {"team_id": 1610612744, "season": "2024-25"},
    # misc: GLAlum needs person IDs passed through
    "gl_alum_box_score_similarity_score": {
        "person1_id": 201939,
        "person2_id": 201566,
    },
    # misc: PlayerFantasyProfile requires player_id + optional season
    "player_fantasy_profile": {"player_id": 201939, "season": "2024-25"},
    "video_details": {"player_id": 201939, "team_id": 1610612744, "season": "2024-25"},
    "video_details_asset": {
        "player_id": 201939,
        "team_id": 1610612744,
        "season": "2024-25",
    },
    # misc: LeagueGameFinder / TeamGameStreakFinder pass **params
    "league_game_finder": {"season": "2024-25"},
    "team_game_streak_finder": {"season": "2024-25"},
    "video_events": {"game_id": "0022400001"},
    "video_status": {"game_date": "2024-10-22", "league_id": "00"},
    # hustle: HustleStatsBoxScore needs game_id
    "hustle_stats_box_score": {"game_id": "0022400001"},
    # team_info: FranchiseHistory needs no params
    "franchise_history": {},
    # team_info: CommonTeamYears needs no params
    "common_team_years": {},
    # team_info: TeamEstimatedMetrics only needs season (no team_id)
    "team_estimated_metrics": {"season": "2024-25"},
    # shots: ShotChartDetail has all optional params with defaults
    "shot_chart_detail": {"season": "2024-25"},
    # shots: ShotChartLineupDetail needs season
    "shot_chart_lineup_detail": {"season": "2024-25"},
}

# Category defaults — used when endpoint_name is NOT in _EXTRACT_PARAMS.
_CATEGORY_DEFAULTS: dict[str, dict[str, object]] = {
    "box_score": {"game_id": "0022400001"},
    "play_by_play": {"game_id": "0022400001"},
    "game_log": {"season": "2024-25"},
    "player_info": {"player_id": 201939, "season": "2024-25"},
    "team_info": {"team_id": 1610612744, "season": "2024-25"},
    "draft": {"season": "2024-25"},
    "standings": {"season": "2024-25"},
    "shots": {"player_id": 201939, "season": "2024-25"},
    "league": {"season": "2024-25"},
    "schedule": {"season": "2024-25"},
    "rotation": {"game_id": "0022400001"},
    "synergy": {"season": "2024-25"},
    "hustle": {"season": "2024-25"},
    "tracking": {"season": "2024-25"},
    "leaders": {"season": "2024-25"},
    "misc": {"season": "2024-25"},
    "franchise": {"team_id": 1610612744},
}


def _get_params(endpoint_name: str, category: str) -> dict[str, object]:
    """Return the params dict for a given extractor."""
    if endpoint_name in _EXTRACT_PARAMS:
        return _EXTRACT_PARAMS[endpoint_name]
    return _CATEGORY_DEFAULTS.get(category, {"season": "2024-25"})


# Combine _ALL_EXTRACTORS + aliased extractors not in the main list.
_ALL_WITH_ALIASES = _ALL_EXTRACTORS + [
    (PlayerDashGameSplitsExtractor, "player_dash_game_splits", "player_info"),
    (PlayerDashGeneralSplitsExtractor, "player_dash_general_splits", "player_info"),
    (PlayerDashLastNGamesExtractor, "player_dash_last_n_games", "player_info"),
    (PlayerDashShootingSplitsExtractor, "player_dash_shooting_splits", "player_info"),
    (PlayerDashTeamPerfExtractor, "player_dash_team_perf", "player_info"),
    (PlayerDashYoyExtractor, "player_dash_yoy", "player_info"),
]


@pytest.mark.parametrize(
    "cls, endpoint_name, category",
    _ALL_WITH_ALIASES,
    ids=[t[1] for t in _ALL_WITH_ALIASES],
)
class TestExtractMethodCoverage:
    """Verify every extractor's extract() runs through _from_nba_api."""

    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(
        self,
        cls: type,
        endpoint_name: str,
        category: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        dummy_df = pl.DataFrame({"col": [1, 2, 3]})

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            return dummy_df

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        params = _get_params(endpoint_name, category)
        result = await ext.extract(**params)
        assert isinstance(result, pl.DataFrame)


# ---------------------------------------------------------------------------
# extract_all method coverage for extractors with multi-result endpoints
# ---------------------------------------------------------------------------

# (cls, endpoint_name, params_dict)
_TEAM_PARAMS = {"team_id": 1610612744, "season": "2024-25"}
_GAME_PARAMS = {"game_id": "0022400001"}

_EXTRACT_ALL_CASES = [
    # team_tracking: 3 extractors with extract_all
    (TeamDashPtShotsExtractor, "team_dash_pt_shots_all", _TEAM_PARAMS),
    (TeamDashPtPassExtractor, "team_dash_pt_pass_all", _TEAM_PARAMS),
    (TeamDashPtRebExtractor, "team_dash_pt_reb_all", _TEAM_PARAMS),
    # box_summary: 2 extractors with extract_all
    (BoxScoreSummaryExtractor, "box_score_summary_all", _GAME_PARAMS),
    (BoxScoreSummaryV3Extractor, "box_score_summary_v3_all", _GAME_PARAMS),
    # hustle: HustleStatsBoxScore extract_all
    (HustleStatsBoxScoreExtractor, "hustle_box_score_all", _GAME_PARAMS),
]


@pytest.mark.parametrize(
    "cls, test_id, params",
    _EXTRACT_ALL_CASES,
    ids=[t[1] for t in _EXTRACT_ALL_CASES],
)
class TestExtractAllMethodCoverage:
    """Verify extract_all() on extractors that support multi-result sets."""

    @pytest.mark.asyncio
    async def test_extract_all_returns_list(
        self,
        cls: type,
        test_id: str,
        params: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        dummy_dfs = [
            pl.DataFrame({"col": [1]}),
            pl.DataFrame({"col": [2]}),
        ]

        def _fake_multi(endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
            return dummy_dfs

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake_multi)
        result = await ext.extract_all(**params)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(df, pl.DataFrame) for df in result)


# team_tracking: extract_all with explicit season_type param
class TestTeamTrackingExtractAllSeasonType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cls",
        [TeamDashPtShotsExtractor, TeamDashPtPassExtractor, TeamDashPtRebExtractor],
        ids=["shots", "pass", "reb"],
    )
    async def test_extract_all_passes_season_type(
        self,
        cls: type,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        captured: dict[str, object] = {}

        def _fake_multi(endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
            captured.update(kwargs)
            return [pl.DataFrame({"ok": [1]})]

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake_multi)
        await ext.extract_all(
            team_id=1610612744, season="2024-25", season_type="Playoffs"
        )
        assert captured["season_type_all_star"] == "Playoffs"


# hustle: LeagueHustlePlayerExtractor and LeagueHustleTeamExtractor extract()
class TestHustleExtractors:
    @pytest.mark.asyncio
    async def test_league_hustle_player_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = LeagueHustlePlayerExtractor()
        dummy_df = pl.DataFrame({"col": [1]})
        monkeypatch.setattr(ext, "_from_nba_api", lambda endpoint_cls, **kw: dummy_df)
        result = await ext.extract(season="2024-25")
        assert isinstance(result, pl.DataFrame)

    @pytest.mark.asyncio
    async def test_league_hustle_team_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = LeagueHustleTeamExtractor()
        dummy_df = pl.DataFrame({"col": [1]})
        monkeypatch.setattr(ext, "_from_nba_api", lambda endpoint_cls, **kw: dummy_df)
        result = await ext.extract(season="2024-25")
        assert isinstance(result, pl.DataFrame)

    @pytest.mark.asyncio
    async def test_league_hustle_player_extract_with_season_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ext = LeagueHustlePlayerExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", season_type="Playoffs")
        assert captured["season_type_all_star"] == "Playoffs"

    @pytest.mark.asyncio
    async def test_league_hustle_team_extract_with_season_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ext = LeagueHustleTeamExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", season_type="Playoffs")
        assert captured["season_type_all_star"] == "Playoffs"


# player_game_log: PlayerGameLogsV2Extractor and PlayerStreakFinderExtractor extract()
class TestPlayerGameLogV2Extractors:
    @pytest.mark.asyncio
    async def test_player_game_logs_v2_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayerGameLogsV2Extractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(player_id=2544, season="2024-25", season_type="Playoffs")
        assert isinstance(result, pl.DataFrame)
        assert captured["player_id_nullable"] == 2544
        assert captured["season_nullable"] == "2024-25"
        assert captured["season_type_nullable"] == "Playoffs"

    @pytest.mark.asyncio
    async def test_player_streak_finder_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayerStreakFinderExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(player_id=2544, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert captured["player_id_nullable"] == 2544
        assert captured["season_nullable"] == "2024-25"


# ---------------------------------------------------------------------------
# SynergyPlayTypesExtractor — all-combination coverage (HR-T-002)
# ---------------------------------------------------------------------------


class TestSynergyPlayTypesExtractor:
    @pytest.fixture
    def synergy_ext(self):
        from nbadb.extract.stats.synergy import SynergyPlayTypesExtractor

        return SynergyPlayTypesExtractor()

    @pytest.mark.asyncio
    async def test_iterates_all_combinations(self, synergy_ext, monkeypatch):
        calls: list[dict] = []

        def _fake(endpoint_cls, **kw):
            calls.append(kw)
            return pl.DataFrame({"val": [1]})

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _fake)
        # Disable the inter-call sleep for test speed
        monkeypatch.setattr("nbadb.extract.stats.synergy.time.sleep", lambda _: None)
        result = await synergy_ext.extract(season="2024-25")

        assert len(calls) == 44  # 11 play_types × 2 entity_types × 2 groupings
        assert "play_type" in result.columns
        assert "entity_type" in result.columns
        assert "type_grouping" in result.columns
        assert result.shape[0] == 44

    @pytest.mark.asyncio
    async def test_individual_failure_continues(self, synergy_ext, monkeypatch):
        call_count = 0

        def _fake(endpoint_cls, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 5:
                raise ConnectionError("test failure")
            return pl.DataFrame({"val": [1]})

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _fake)
        monkeypatch.setattr("nbadb.extract.stats.synergy.time.sleep", lambda _: None)
        result = await synergy_ext.extract(season="2024-25")

        assert result.shape[0] == 43  # 44 - 1 failure
        assert call_count == 44  # all combinations still attempted

    @pytest.mark.asyncio
    async def test_all_failures_raises(self, synergy_ext, monkeypatch):
        def _fake(endpoint_cls, **kw):
            raise ConnectionError("all fail")

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _fake)
        monkeypatch.setattr("nbadb.extract.stats.synergy.time.sleep", lambda _: None)

        with pytest.raises(RuntimeError, match="all 44 synergy combinations failed"):
            await synergy_ext.extract(season="2024-25")
