# ruff: noqa: I001

# ruff: noqa: I001

from __future__ import annotations

import pytest

from nbadb.schemas.registry import get_input_schema, get_output_schema
from nbadb.schemas.staging.misc_static_support import (
    StagingLeagueGameFinderSchema,
    StagingMatchupsRollupSchema,
    StagingPlayByPlayVideoAvailableSchema,
    StagingScheduleWeeksSchema,
    StagingSeasonMatchupsSchema,
    StagingStaticPlayersSchema,
    StagingStaticTeamsSchema,
    StagingTeamStreakFinderSchema,
)
from nbadb.schemas.staging.playoff_shot_support import (
    StagingPlayoffPictureEastRemainingSchema,
    StagingPlayoffPictureEastStandingsSchema,
    StagingPlayoffPictureWestRemainingSchema,
    StagingPlayoffPictureWestStandingsSchema,
    StagingShotChartLeagueAveragesSchema,
    StagingShotChartLineupDetailSchema,
    StagingShotChartLineupLeagueAvgSchema,
    StagingShotChartLineupSchema,
)
from nbadb.schemas.star.misc_static_support import (
    FactLeagueGameFinderSchema,
    FactSeasonMatchupsSchema,
    FactStaticPlayersSchema,
    FactStaticTeamsSchema,
    FactStreakFinderSchema,
    FactTeamStreakFinderSchema,
)
from nbadb.schemas.star.playoff_shot_support import (
    FactPlayoffPictureSchema,
    FactShotChartLeagueSchema,
    FactShotChartLineupSchema,
)


@pytest.mark.parametrize(
    ("table_name", "expected_schema"),
    [
        ("stg_league_game_finder", StagingLeagueGameFinderSchema),
        ("stg_season_matchups", StagingSeasonMatchupsSchema),
        ("stg_matchups_rollup", StagingMatchupsRollupSchema),
        ("stg_play_by_play_video_available", StagingPlayByPlayVideoAvailableSchema),
        ("stg_playoff_picture_east_remaining", StagingPlayoffPictureEastRemainingSchema),
        ("stg_playoff_picture_east_standings", StagingPlayoffPictureEastStandingsSchema),
        ("stg_playoff_picture_west_remaining", StagingPlayoffPictureWestRemainingSchema),
        ("stg_playoff_picture_west_standings", StagingPlayoffPictureWestStandingsSchema),
        ("stg_schedule_weeks", StagingScheduleWeeksSchema),
        ("stg_shot_chart_league_averages", StagingShotChartLeagueAveragesSchema),
        ("stg_shot_chart_lineup", StagingShotChartLineupSchema),
        ("stg_shot_chart_lineup_detail", StagingShotChartLineupDetailSchema),
        ("stg_shot_chart_lineup_league_avg", StagingShotChartLineupLeagueAvgSchema),
        ("stg_static_players", StagingStaticPlayersSchema),
        ("stg_static_teams", StagingStaticTeamsSchema),
        ("stg_team_streak_finder", StagingTeamStreakFinderSchema),
    ],
)
def test_get_input_schema_returns_misc_static_playoff_shot_support_contracts(
    table_name: str,
    expected_schema: type,
) -> None:
    assert get_input_schema(table_name) is expected_schema


@pytest.mark.parametrize(
    ("table_name", "expected_schema"),
    [
        ("fact_league_game_finder", FactLeagueGameFinderSchema),
        ("fact_season_matchups", FactSeasonMatchupsSchema),
        ("fact_playoff_picture", FactPlayoffPictureSchema),
        ("fact_shot_chart_league", FactShotChartLeagueSchema),
        ("fact_shot_chart_lineup", FactShotChartLineupSchema),
        ("fact_static_players", FactStaticPlayersSchema),
        ("fact_streak_finder", FactStreakFinderSchema),
        ("fact_static_teams", FactStaticTeamsSchema),
        ("fact_team_streak_finder", FactTeamStreakFinderSchema),
    ],
)
def test_get_output_schema_returns_misc_static_playoff_shot_star_contracts(
    table_name: str,
    expected_schema: type,
) -> None:
    assert get_output_schema(table_name) is expected_schema
