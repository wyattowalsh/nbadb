# ruff: noqa: I001
from __future__ import annotations

import pytest

from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.orchestrate.transformers import discover_all_transformers
from nbadb.schemas.raw.live import RawLiveScoreBoardSchema
from nbadb.schemas.raw.misc import RawDunkScoreLeadersSchema, RawGravityLeadersSchema
from nbadb.schemas.raw.player_info import RawCommonPlayerInfoSchema
from nbadb.schemas.registry import (
    _INPUT_SCHEMA_ALIASES,
    _raw_schema_registry,
    _staging_schema_registry,
    get_input_schema,
    get_output_schema,
)
from nbadb.schemas.staging.leaders import (
    StagingAllTimeAstSchema,
    StagingCumePlayerGameByGameSchema,
    StagingDraftBoardSchema,
    StagingHomepageLeadersSchema,
    StagingHomepageV2Schema,
    StagingLeadersTilesSchema,
    StagingLeagueLeadersSchema,
)
from nbadb.schemas.staging.player_team_family_support import StagingTeamShoot5FtSchema
from nbadb.schemas.staging.live import StagingLiveScoreBoardSchema
from nbadb.schemas.staging.misc import (
    StagingVideoDetailsAssetSchema,
    StagingVideoDetailsSchema,
    StagingVideoEventsSchema,
    StagingVideoStatusSchema,
)
from nbadb.schemas.staging.play_by_play import StagingPlayByPlayV2VideoAvailableSchema
from nbadb.schemas.staging.schedule import (
    StagingScheduleIntBroadcasterSchema,
    StagingScheduleIntSchema,
    StagingScheduleIntWeeksSchema,
    StagingScheduleLeagueV2Schema,
)
from nbadb.schemas.star.dim_team import DimTeamSchema
from nbadb.schemas.star.fact_play_by_play_v2_support import (
    FactPlayByPlayV2Schema,
    FactPlayByPlayV2VideoSchema,
)
from nbadb.schemas.star.fact_player_support_exceptions import (
    FactPlayerIndexSchema,
    FactPlayerMatchupsPlayerInfoSchema,
)
from nbadb.schemas.star.fact_cumulative_stats import (
    FactCumulativeStatsDetailSchema,
    FactCumulativeStatsSchema,
)
from nbadb.schemas.star.fact_draft import FactDraftCombineStatsSchema, FactDraftHistorySchema
from nbadb.schemas.star.fact_draft_board import FactDraftBoardSchema
from nbadb.schemas.star.fact_fantasy_family import (
    FactFantasyWidgetSchema,
    FactInfographicFanduelPlayerSchema,
    FactPlayerFantasyProfileLastFiveGamesAvgSchema,
    FactPlayerFantasyProfileSeasonAvgSchema,
)
from nbadb.schemas.star.fact_league_support import (
    FactDraftCombineDrillResultsSchema,
    FactDraftCombineNonStationaryShootingSchema,
    FactDraftCombinePlayerAnthroSchema,
    FactDraftCombineSpotShootingSchema,
)
from nbadb.schemas.star.fact_leader_family import (
    FactAssistLeadersSchema,
    FactAssistTrackerSchema,
    FactDunkScoreLeadersSchema,
    FactGravityLeadersSchema,
    FactLeagueLeadersSchema,
)
from nbadb.schemas.star.fact_league_leaders_detail import FactLeagueLeadersDetailSchema
from nbadb.schemas.star.player_team_family_support import (
    FactFranchiseLeadersSchema,
    FactFranchisePlayersSchema,
)
from nbadb.schemas.star.fact_video_support import (
    FactVideoDetailsAssetSchema,
    FactVideoDetailsSchema,
    FactVideoEventsSchema,
    FactVideoStatusSchema,
)
from nbadb.schemas.star.live import FactLiveScoreBoardSchema


def test_get_input_schema_returns_direct_staging_schema() -> None:
    assert get_input_schema("stg_schedule_league_v2") is StagingScheduleLeagueV2Schema


def test_get_input_schema_returns_direct_raw_schema() -> None:
    assert get_input_schema("raw_common_player_info") is RawCommonPlayerInfoSchema


def test_get_input_schema_returns_live_raw_schema() -> None:
    assert get_input_schema("raw_live_score_board") is RawLiveScoreBoardSchema


def test_get_input_schema_returns_misc_raw_leader_schemas() -> None:
    assert get_input_schema("raw_dunk_score_leaders") is RawDunkScoreLeadersSchema
    assert get_input_schema("raw_gravity_leaders") is RawGravityLeadersSchema


def test_get_input_schema_returns_live_staging_schema() -> None:
    assert get_input_schema("stg_live_score_board") is StagingLiveScoreBoardSchema


def test_get_input_schema_returns_alias_target_schema() -> None:
    assert get_input_schema("stg_player_info") is RawCommonPlayerInfoSchema


def test_get_input_schema_returns_numeric_packet_alias_schema() -> None:
    assert get_input_schema("stg_team_shoot_5ft") is StagingTeamShoot5FtSchema


def test_get_output_schema_returns_star_schema() -> None:
    assert get_output_schema("dim_team") is DimTeamSchema


def test_get_output_schema_returns_live_star_schema() -> None:
    assert get_output_schema("fact_live_score_board") is FactLiveScoreBoardSchema


def test_all_staging_map_keys_resolve_to_input_schemas() -> None:
    missing = sorted(
        staging_key
        for staging_key in {entry.staging_key for entry in STAGING_MAP}
        if get_input_schema(staging_key) is None
    )

    assert missing == []


def test_all_input_schema_alias_targets_resolve() -> None:
    schema_keys = set(_staging_schema_registry()) | set(_raw_schema_registry())
    unresolved = sorted(
        target for target in set(_INPUT_SCHEMA_ALIASES.values()) if target not in schema_keys
    )

    assert unresolved == []


def test_all_discovered_transform_outputs_have_star_schemas() -> None:
    missing = sorted(
        transformer.output_table
        for transformer in discover_all_transformers(include_live=True)
        if get_output_schema(transformer.output_table) is None
    )

    assert missing == []


@pytest.mark.parametrize(
    ("table_name", "expected_schema"),
    [
        ("stg_all_time", StagingAllTimeAstSchema),
        ("stg_league_leaders", StagingLeagueLeadersSchema),
        ("stg_cume_player", StagingCumePlayerGameByGameSchema),
        ("stg_draft_board", StagingDraftBoardSchema),
        ("stg_homepage_leaders_main", StagingHomepageLeadersSchema),
        ("stg_home_page_v2", StagingHomepageV2Schema),
        ("stg_leaders_tiles_alltime_high", StagingLeadersTilesSchema),
        ("stg_play_by_play_v2_video_available", StagingPlayByPlayV2VideoAvailableSchema),
        ("stg_schedule_int", StagingScheduleIntSchema),
        ("stg_schedule_int_broadcaster", StagingScheduleIntBroadcasterSchema),
        ("stg_schedule_int_weeks", StagingScheduleIntWeeksSchema),
        ("stg_video_details", StagingVideoDetailsSchema),
        ("stg_video_details_asset", StagingVideoDetailsAssetSchema),
        ("stg_video_events", StagingVideoEventsSchema),
        ("stg_video_status", StagingVideoStatusSchema),
    ],
)
def test_get_input_schema_returns_leader_family_support_contracts(
    table_name: str,
    expected_schema: type,
) -> None:
    assert get_input_schema(table_name) is expected_schema


@pytest.mark.parametrize(
    ("table_name", "expected_schema"),
    [
        ("fact_assist_leaders", FactAssistLeadersSchema),
        ("fact_assist_tracker", FactAssistTrackerSchema),
        ("fact_league_leaders_detail", FactLeagueLeadersDetailSchema),
        ("fact_league_leaders", FactLeagueLeadersSchema),
        ("fact_dunk_score_leaders", FactDunkScoreLeadersSchema),
        ("fact_gravity_leaders", FactGravityLeadersSchema),
        ("fact_fantasy_widget", FactFantasyWidgetSchema),
        ("fact_infographic_fanduel_player", FactInfographicFanduelPlayerSchema),
        (
            "fact_player_fantasy_profile_last_five_games_avg",
            FactPlayerFantasyProfileLastFiveGamesAvgSchema,
        ),
        ("fact_player_fantasy_profile_season_avg", FactPlayerFantasyProfileSeasonAvgSchema),
        ("fact_cumulative_stats", FactCumulativeStatsSchema),
        ("fact_cumulative_stats_detail", FactCumulativeStatsDetailSchema),
        ("fact_draft_board", FactDraftBoardSchema),
        ("fact_draft_combine_drill_results", FactDraftCombineDrillResultsSchema),
        ("fact_draft_combine_non_stationary_shooting", FactDraftCombineNonStationaryShootingSchema),
        ("fact_draft_combine_player_anthro", FactDraftCombinePlayerAnthroSchema),
        ("fact_draft_combine_spot_shooting", FactDraftCombineSpotShootingSchema),
        ("fact_draft_combine_stats", FactDraftCombineStatsSchema),
        ("fact_draft_history", FactDraftHistorySchema),
        ("fact_franchise_leaders", FactFranchiseLeadersSchema),
        ("fact_franchise_players", FactFranchisePlayersSchema),
        ("fact_play_by_play_v2", FactPlayByPlayV2Schema),
        ("fact_play_by_play_v2_video", FactPlayByPlayV2VideoSchema),
        ("fact_player_index", FactPlayerIndexSchema),
        ("fact_player_matchups_player_info", FactPlayerMatchupsPlayerInfoSchema),
        ("fact_video_details", FactVideoDetailsSchema),
        ("fact_video_details_asset", FactVideoDetailsAssetSchema),
        ("fact_video_events", FactVideoEventsSchema),
        ("fact_video_status", FactVideoStatusSchema),
    ],
)
def test_get_output_schema_returns_leader_family_star_contracts(
    table_name: str,
    expected_schema: type,
) -> None:
    assert get_output_schema(table_name) is expected_schema
