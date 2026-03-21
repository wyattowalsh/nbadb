from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_cumulative_stats import FactCumulativeStatsTransformer
from nbadb.transform.facts.fact_draft_board import FactDraftBoardTransformer
from nbadb.transform.facts.fact_draft_combine_detail import FactDraftCombineDetailTransformer
from nbadb.transform.facts.fact_fantasy import FactFantasyTransformer
from nbadb.transform.facts.fact_franchise_detail import FactFranchiseDetailTransformer
from nbadb.transform.facts.fact_game_context import FactGameContextTransformer
from nbadb.transform.facts.fact_ist_standings import FactIstStandingsTransformer
from nbadb.transform.facts.fact_league_hustle import FactLeagueHustleTransformer
from nbadb.transform.facts.fact_league_leaders_detail import FactLeagueLeadersDetailTransformer
from nbadb.transform.facts.fact_league_pt_shots import FactLeaguePtShotsTransformer
from nbadb.transform.facts.fact_player_career import FactPlayerCareerTransformer
from nbadb.transform.facts.fact_player_matchups import FactPlayerMatchupsTransformer
from nbadb.transform.facts.fact_player_profile import FactPlayerProfileTransformer
from nbadb.transform.facts.fact_player_pt_tracking import FactPlayerPtTrackingTransformer
from nbadb.transform.facts.fact_player_season_ranks import FactPlayerSeasonRanksTransformer
from nbadb.transform.facts.fact_player_splits import FactPlayerSplitsTransformer
from nbadb.transform.facts.fact_playoff_picture import FactPlayoffPictureTransformer
from nbadb.transform.facts.fact_playoff_series import FactPlayoffSeriesTransformer
from nbadb.transform.facts.fact_season_matchups import FactSeasonMatchupsTransformer
from nbadb.transform.facts.fact_streak_finder import FactStreakFinderTransformer
from nbadb.transform.facts.fact_team_historical import FactTeamHistoricalTransformer
from nbadb.transform.facts.fact_team_matchups import FactTeamMatchupsTransformer
from nbadb.transform.facts.fact_team_pt_tracking import FactTeamPtTrackingTransformer
from nbadb.transform.facts.fact_team_splits import FactTeamSplitsTransformer


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    transformer._conn = conn
    result = transformer.transform(staging)
    conn.close()
    return result


# ---------------------------------------------------------------------------
# 1. fact_playoff_picture
# ---------------------------------------------------------------------------
class TestFactPlayoffPicture:
    def test_class_attrs(self) -> None:
        assert FactPlayoffPictureTransformer.output_table == "fact_playoff_picture"
        assert len(FactPlayoffPictureTransformer.depends_on) == 6

    def test_transform_produces_conference_column(self) -> None:
        east = pl.DataFrame({"team_id": [1], "seed": [1]}).lazy()
        east_standings = pl.DataFrame({"team_id": [1], "wins": [50]}).lazy()
        east_remaining = pl.DataFrame({"team_id": [1], "games_remaining": [5]}).lazy()
        west = pl.DataFrame({"team_id": [2], "seed": [1]}).lazy()
        west_standings = pl.DataFrame({"team_id": [2], "wins": [48]}).lazy()
        west_remaining = pl.DataFrame({"team_id": [2], "games_remaining": [7]}).lazy()
        staging = {
            "stg_playoff_picture_east": east,
            "stg_playoff_picture_east_standings": east_standings,
            "stg_playoff_picture_east_remaining": east_remaining,
            "stg_playoff_picture_west": west,
            "stg_playoff_picture_west_standings": west_standings,
            "stg_playoff_picture_west_remaining": west_remaining,
        }
        t = FactPlayoffPictureTransformer()
        result = _run(t, staging)
        assert result.shape[0] == 2
        assert "conference" in result.columns
        assert set(result["conference"].to_list()) == {"East", "West"}

    def test_join_adds_standings_and_remaining_cols(self) -> None:
        staging = {
            "stg_playoff_picture_east": pl.DataFrame({"team_id": [10]}).lazy(),
            "stg_playoff_picture_east_standings": pl.DataFrame(
                {"team_id": [10], "wins": [42]}
            ).lazy(),
            "stg_playoff_picture_east_remaining": pl.DataFrame(
                {"team_id": [10], "remaining": [8]}
            ).lazy(),
            "stg_playoff_picture_west": pl.DataFrame({"team_id": [20]}).lazy(),
            "stg_playoff_picture_west_standings": pl.DataFrame(
                {"team_id": [20], "wins": [39]}
            ).lazy(),
            "stg_playoff_picture_west_remaining": pl.DataFrame(
                {"team_id": [20], "remaining": [10]}
            ).lazy(),
        }
        result = _run(FactPlayoffPictureTransformer(), staging)
        assert "wins" in result.columns
        assert "remaining" in result.columns


# ---------------------------------------------------------------------------
# 2. fact_playoff_series
# ---------------------------------------------------------------------------
class TestFactPlayoffSeries:
    def test_class_attrs(self) -> None:
        assert FactPlayoffSeriesTransformer.output_table == "fact_playoff_series"
        assert "stg_common_playoff_series" in FactPlayoffSeriesTransformer.depends_on

    def test_transform_passthrough(self) -> None:
        staging = {
            "stg_common_playoff_series": pl.DataFrame(
                {"series_id": ["A"], "home_team_id": [1], "away_team_id": [2]}
            ).lazy(),
        }
        result = _run(FactPlayoffSeriesTransformer(), staging)
        assert result.shape[0] == 1
        assert "series_id" in result.columns


# ---------------------------------------------------------------------------
# 3. fact_ist_standings
# ---------------------------------------------------------------------------
class TestFactIstStandings:
    def test_class_attrs(self) -> None:
        assert FactIstStandingsTransformer.output_table == "fact_ist_standings"
        assert "stg_ist_standings" in FactIstStandingsTransformer.depends_on

    def test_transform_passthrough(self) -> None:
        staging = {
            "stg_ist_standings": pl.DataFrame(
                {"team_id": [1], "group_name": ["East A"], "wins": [3]}
            ).lazy(),
        }
        result = _run(FactIstStandingsTransformer(), staging)
        assert result.shape[0] == 1
        assert set(result.columns) == {"team_id", "group_name", "wins"}


# ---------------------------------------------------------------------------
# 4. fact_draft_board
# ---------------------------------------------------------------------------
class TestFactDraftBoard:
    def test_class_attrs(self) -> None:
        assert FactDraftBoardTransformer.output_table == "fact_draft_board"
        assert "stg_draft_board" in FactDraftBoardTransformer.depends_on

    def test_transform_passthrough(self) -> None:
        staging = {
            "stg_draft_board": pl.DataFrame(
                {"player_id": [101], "pick_number": [1], "season_year": [2024]}
            ).lazy(),
        }
        result = _run(FactDraftBoardTransformer(), staging)
        assert result.shape[0] == 1
        assert "player_id" in result.columns


# ---------------------------------------------------------------------------
# 5. fact_player_career — UNION ALL BY NAME with career_type
# ---------------------------------------------------------------------------
class TestFactPlayerCareer:
    def test_class_attrs(self) -> None:
        assert FactPlayerCareerTransformer.output_table == "fact_player_career"
        assert len(FactPlayerCareerTransformer.depends_on) == 8

    def test_union_with_career_type(self) -> None:
        staging = {
            "stg_player_career_total_regular": pl.DataFrame(
                {"player_id": [1], "pts": [100]}
            ).lazy(),
            "stg_player_career_total_postseason": pl.DataFrame(
                {"player_id": [2], "pts": [50]}
            ).lazy(),
            "stg_player_career_total_allstar": pl.DataFrame(
                {"player_id": [5], "pts": [25]}
            ).lazy(),
            "stg_player_career_total_college": pl.DataFrame(
                {"player_id": [6], "pts": [15]}
            ).lazy(),
            "stg_player_career_allstar": pl.DataFrame({"player_id": [3], "pts": [30]}).lazy(),
            "stg_player_career_college": pl.DataFrame({"player_id": [4], "pts": [80]}).lazy(),
            "stg_player_career_regular": pl.DataFrame({"player_id": [7], "pts": [90]}).lazy(),
            "stg_player_career_postseason": pl.DataFrame(
                {"player_id": [8], "pts": [40]}
            ).lazy(),
        }
        result = _run(FactPlayerCareerTransformer(), staging)
        assert result.shape[0] == 8
        assert "career_type" in result.columns
        assert set(result["career_type"].to_list()) == {
            "regular",
            "postseason",
            "total_allstar",
            "total_college",
            "allstar",
            "college",
            "season_regular",
            "season_postseason",
        }


# ---------------------------------------------------------------------------
# 6. fact_player_season_ranks — UNION ALL BY NAME with rank_type
# ---------------------------------------------------------------------------
class TestFactPlayerSeasonRanks:
    def test_class_attrs(self) -> None:
        assert FactPlayerSeasonRanksTransformer.output_table == "fact_player_season_ranks"
        assert len(FactPlayerSeasonRanksTransformer.depends_on) == 2

    def test_union_with_rank_type(self) -> None:
        staging = {
            "stg_player_season_ranks_regular": pl.DataFrame({"player_id": [1], "rank": [5]}).lazy(),
            "stg_player_season_ranks_postseason": pl.DataFrame(
                {"player_id": [2], "rank": [10]}
            ).lazy(),
        }
        result = _run(FactPlayerSeasonRanksTransformer(), staging)
        assert result.shape[0] == 2
        assert "rank_type" in result.columns
        assert set(result["rank_type"].to_list()) == {"regular", "postseason"}


# ---------------------------------------------------------------------------
# 7. fact_player_profile — UNION ALL BY NAME with profile_type
# ---------------------------------------------------------------------------
class TestFactPlayerProfile:
    def test_class_attrs(self) -> None:
        assert FactPlayerProfileTransformer.output_table == "fact_player_profile"
        assert len(FactPlayerProfileTransformer.depends_on) == 15

    def test_union_with_profile_type(self) -> None:
        staging = {
            "stg_player_profile_career_highs": pl.DataFrame(
                {"player_id": [1], "value": [60]}
            ).lazy(),
            "stg_player_profile_season_highs": pl.DataFrame(
                {"player_id": [2], "value": [55]}
            ).lazy(),
            "stg_player_profile_next_game": pl.DataFrame(
                {"player_id": [3], "value": [0]}
            ).lazy(),
            "stg_player_profile_regular": pl.DataFrame(
                {"player_id": [4], "value": [10]}
            ).lazy(),
            "stg_player_profile_postseason": pl.DataFrame(
                {"player_id": [5], "value": [11]}
            ).lazy(),
            "stg_player_profile_allstar": pl.DataFrame(
                {"player_id": [6], "value": [12]}
            ).lazy(),
            "stg_player_profile_college": pl.DataFrame(
                {"player_id": [7], "value": [13]}
            ).lazy(),
            "stg_player_profile_preseason": pl.DataFrame(
                {"player_id": [8], "value": [14]}
            ).lazy(),
            "stg_player_profile_ranks_regular": pl.DataFrame(
                {"player_id": [9], "value": [15]}
            ).lazy(),
            "stg_player_profile_ranks_postseason": pl.DataFrame(
                {"player_id": [10], "value": [16]}
            ).lazy(),
            "stg_player_profile_total_regular": pl.DataFrame(
                {"player_id": [11], "value": [17]}
            ).lazy(),
            "stg_player_profile_total_postseason": pl.DataFrame(
                {"player_id": [12], "value": [18]}
            ).lazy(),
            "stg_player_profile_total_allstar": pl.DataFrame(
                {"player_id": [13], "value": [19]}
            ).lazy(),
            "stg_player_profile_total_college": pl.DataFrame(
                {"player_id": [14], "value": [20]}
            ).lazy(),
            "stg_player_profile_total_preseason": pl.DataFrame(
                {"player_id": [15], "value": [21]}
            ).lazy(),
        }
        result = _run(FactPlayerProfileTransformer(), staging)
        assert result.shape[0] == 15
        assert "profile_type" in result.columns
        assert set(result["profile_type"].to_list()) == {
            "career_highs",
            "season_highs",
            "next_game",
            "season_regular",
            "season_postseason",
            "season_allstar",
            "season_college",
            "season_preseason",
            "ranks_regular",
            "ranks_postseason",
            "total_regular",
            "total_postseason",
            "total_allstar",
            "total_college",
            "total_preseason",
        }


# ---------------------------------------------------------------------------
# 8. fact_draft_combine_detail — UNION ALL BY NAME with detail_type
# ---------------------------------------------------------------------------
class TestFactDraftCombineDetail:
    def test_class_attrs(self) -> None:
        assert FactDraftCombineDetailTransformer.output_table == "fact_draft_combine_detail"
        assert len(FactDraftCombineDetailTransformer.depends_on) == 4

    def test_union_with_detail_type(self) -> None:
        staging = {
            "stg_draft_combine_drills": pl.DataFrame({"player_id": [1], "result": [10.5]}).lazy(),
            "stg_draft_combine_anthro": pl.DataFrame({"player_id": [2], "height": [78.0]}).lazy(),
            "stg_draft_combine_nonstat_shooting": pl.DataFrame(
                {"player_id": [3], "pct": [0.45]}
            ).lazy(),
            "stg_draft_combine_spot_shooting": pl.DataFrame(
                {"player_id": [4], "pct": [0.50]}
            ).lazy(),
        }
        result = _run(FactDraftCombineDetailTransformer(), staging)
        assert result.shape[0] == 4
        assert "detail_type" in result.columns
        assert set(result["detail_type"].to_list()) == {
            "drills",
            "anthro",
            "nonstat_shooting",
            "spot_shooting",
        }


# ---------------------------------------------------------------------------
# 9. fact_player_splits — UNION ALL BY NAME with split_type (6 tables)
# ---------------------------------------------------------------------------
class TestFactPlayerSplits:
    def test_class_attrs(self) -> None:
        assert FactPlayerSplitsTransformer.output_table == "fact_player_splits"
        assert len(FactPlayerSplitsTransformer.depends_on) == 6

    def test_union_with_split_type(self) -> None:
        staging = {
            "stg_player_dash_game_splits": pl.DataFrame({"player_id": [1], "gp": [10]}).lazy(),
            "stg_player_dash_general_splits": pl.DataFrame({"player_id": [2], "gp": [20]}).lazy(),
            "stg_player_dash_last_n_games": pl.DataFrame({"player_id": [3], "gp": [5]}).lazy(),
            "stg_player_dash_shooting_splits": pl.DataFrame({"player_id": [4], "gp": [15]}).lazy(),
            "stg_player_dash_team_perf": pl.DataFrame({"player_id": [5], "gp": [12]}).lazy(),
            "stg_player_dash_yoy": pl.DataFrame({"player_id": [6], "gp": [8]}).lazy(),
        }
        result = _run(FactPlayerSplitsTransformer(), staging)
        assert result.shape[0] == 6
        assert "split_type" in result.columns
        assert set(result["split_type"].to_list()) == {
            "game_splits",
            "general_splits",
            "last_n_games",
            "shooting_splits",
            "team_perf",
            "yoy",
        }


# ---------------------------------------------------------------------------
# 10. fact_player_pt_tracking — UNION ALL BY NAME with tracking_type
# ---------------------------------------------------------------------------
class TestFactPlayerPtTracking:
    def test_class_attrs(self) -> None:
        assert FactPlayerPtTrackingTransformer.output_table == "fact_player_pt_tracking"
        assert len(FactPlayerPtTrackingTransformer.depends_on) == 6

    def test_union_with_tracking_type(self) -> None:
        staging = {
            "stg_player_pt_pass": pl.DataFrame({"player_id": [1], "val": [10]}).lazy(),
            "stg_player_pt_pass_received": pl.DataFrame({"player_id": [5], "val": [12]}).lazy(),
            "stg_player_pt_reb": pl.DataFrame({"player_id": [2], "val": [8]}).lazy(),
            "stg_player_pt_shots": pl.DataFrame({"player_id": [3], "val": [15]}).lazy(),
            "stg_player_pt_shot_defend": pl.DataFrame({"player_id": [4], "val": [6]}).lazy(),
            "stg_player_dash_pt_defend": pl.DataFrame({"player_id": [6], "val": [7]}).lazy(),
        }
        result = _run(FactPlayerPtTrackingTransformer(), staging)
        assert result.shape[0] == 6
        assert "tracking_type" in result.columns
        assert set(result["tracking_type"].to_list()) == {
            "pass",
            "pass_received",
            "rebound",
            "shots",
            "shot_defend",
            "defense",
        }


# ---------------------------------------------------------------------------
# 11. fact_team_splits — UNION ALL BY NAME with split_type
# ---------------------------------------------------------------------------
class TestFactTeamSplits:
    def test_class_attrs(self) -> None:
        assert FactTeamSplitsTransformer.output_table == "fact_team_splits"
        assert len(FactTeamSplitsTransformer.depends_on) == 2

    def test_union_with_split_type(self) -> None:
        staging = {
            "stg_team_dash_general_splits": pl.DataFrame({"team_id": [1], "gp": [30]}).lazy(),
            "stg_team_dash_shooting_splits": pl.DataFrame(
                {"team_id": [2], "fg_pct": [0.47]}
            ).lazy(),
        }
        result = _run(FactTeamSplitsTransformer(), staging)
        assert result.shape[0] == 2
        assert "split_type" in result.columns
        assert set(result["split_type"].to_list()) == {"general", "shooting"}


# ---------------------------------------------------------------------------
# 12. fact_team_pt_tracking — UNION ALL BY NAME with tracking_type
# ---------------------------------------------------------------------------
class TestFactTeamPtTracking:
    def test_class_attrs(self) -> None:
        assert FactTeamPtTrackingTransformer.output_table == "fact_team_pt_tracking"
        assert len(FactTeamPtTrackingTransformer.depends_on) == 4

    def test_union_with_tracking_type(self) -> None:
        staging = {
            "stg_team_pt_pass": pl.DataFrame({"team_id": [1], "val": [20]}).lazy(),
            "stg_team_pt_pass_received": pl.DataFrame({"team_id": [4], "val": [18]}).lazy(),
            "stg_team_pt_reb": pl.DataFrame({"team_id": [2], "val": [15]}).lazy(),
            "stg_team_pt_shots": pl.DataFrame({"team_id": [3], "val": [25]}).lazy(),
        }
        result = _run(FactTeamPtTrackingTransformer(), staging)
        assert result.shape[0] == 4
        assert "tracking_type" in result.columns
        expected = {"pass", "pass_received", "rebound", "shots"}
        assert set(result["tracking_type"].to_list()) == expected


# ---------------------------------------------------------------------------
# 13. fact_team_historical — UNION ALL BY NAME with history_type
# ---------------------------------------------------------------------------
class TestFactTeamHistorical:
    def test_class_attrs(self) -> None:
        assert FactTeamHistoricalTransformer.output_table == "fact_team_historical"
        assert len(FactTeamHistoricalTransformer.depends_on) == 3

    def test_union_with_history_type(self) -> None:
        staging = {
            "stg_team_historical_leaders": pl.DataFrame(
                {"team_id": [1], "player_name": ["Jordan"]}
            ).lazy(),
            "stg_team_year_by_year": pl.DataFrame({"team_id": [1], "season": ["2023-24"]}).lazy(),
            "stg_team_year_by_year_stats": pl.DataFrame(
                {"team_id": [1], "season": ["2023-24"]}
            ).lazy(),
        }
        result = _run(FactTeamHistoricalTransformer(), staging)
        assert result.shape[0] == 3
        assert "history_type" in result.columns
        assert set(result["history_type"].to_list()) == {
            "leaders",
            "year_by_year",
            "year_by_year_stats",
        }


# ---------------------------------------------------------------------------
# 14. fact_franchise_detail — UNION ALL BY NAME with detail_type
# ---------------------------------------------------------------------------
class TestFactFranchiseDetail:
    def test_class_attrs(self) -> None:
        assert FactFranchiseDetailTransformer.output_table == "fact_franchise_detail"
        assert len(FactFranchiseDetailTransformer.depends_on) == 2

    def test_union_with_detail_type(self) -> None:
        staging = {
            "stg_franchise_leaders": pl.DataFrame(
                {"franchise_id": [1], "player_name": ["LeBron"]}
            ).lazy(),
            "stg_franchise_players": pl.DataFrame(
                {"franchise_id": [1], "player_name": ["Kobe"]}
            ).lazy(),
        }
        result = _run(FactFranchiseDetailTransformer(), staging)
        assert result.shape[0] == 2
        assert "detail_type" in result.columns
        assert set(result["detail_type"].to_list()) == {"leaders", "players"}


# ---------------------------------------------------------------------------
# 15. fact_league_hustle — UNION ALL BY NAME with entity_type
# ---------------------------------------------------------------------------
class TestFactLeagueHustle:
    def test_class_attrs(self) -> None:
        assert FactLeagueHustleTransformer.output_table == "fact_league_hustle"
        assert len(FactLeagueHustleTransformer.depends_on) == 2

    def test_union_with_entity_type(self) -> None:
        staging = {
            "stg_league_hustle_player": pl.DataFrame({"player_id": [1], "deflections": [5]}).lazy(),
            "stg_league_hustle_team": pl.DataFrame({"team_id": [10], "deflections": [40]}).lazy(),
        }
        result = _run(FactLeagueHustleTransformer(), staging)
        assert result.shape[0] == 2
        assert "entity_type" in result.columns
        assert set(result["entity_type"].to_list()) == {"player", "team"}


# ---------------------------------------------------------------------------
# 16. fact_league_leaders_detail — UNION ALL BY NAME with leader_type (5 tables)
# ---------------------------------------------------------------------------
class TestFactLeagueLeadersDetail:
    def test_class_attrs(self) -> None:
        assert FactLeagueLeadersDetailTransformer.output_table == "fact_league_leaders_detail"
        assert len(FactLeagueLeadersDetailTransformer.depends_on) == 5

    def test_union_with_leader_type(self) -> None:
        staging = {
            "stg_league_leaders": pl.DataFrame({"player_id": [1], "pts": [30]}).lazy(),
            "stg_assist_leaders": pl.DataFrame({"player_id": [2], "ast": [12]}).lazy(),
            "stg_assist_tracker": pl.DataFrame({"player_id": [3], "ast": [10]}).lazy(),
            "stg_dunk_score_leaders": pl.DataFrame({"player_id": [4], "dunks": [8]}).lazy(),
            "stg_gravity_leaders": pl.DataFrame({"player_id": [5], "gravity": [1.5]}).lazy(),
        }
        result = _run(FactLeagueLeadersDetailTransformer(), staging)
        assert result.shape[0] == 5
        assert "leader_type" in result.columns
        assert set(result["leader_type"].to_list()) == {
            "league",
            "assist",
            "assist_tracker",
            "dunk_score",
            "gravity",
        }


# ---------------------------------------------------------------------------
# 17. fact_league_pt_shots — UNION ALL BY NAME with shot_type (5 tables)
# ---------------------------------------------------------------------------
class TestFactLeaguePtShots:
    def test_class_attrs(self) -> None:
        assert FactLeaguePtShotsTransformer.output_table == "fact_league_pt_shots"
        assert len(FactLeaguePtShotsTransformer.depends_on) == 5

    def test_union_with_shot_type(self) -> None:
        staging = {
            "stg_league_pt_stats": pl.DataFrame({"id": [1], "fga": [20]}).lazy(),
            "stg_league_pt_team_defend": pl.DataFrame({"id": [2], "dfga": [18]}).lazy(),
            "stg_league_team_pt_shot": pl.DataFrame({"id": [3], "fga": [22]}).lazy(),
            "stg_league_opp_pt_shot": pl.DataFrame({"id": [4], "fga": [19]}).lazy(),
            "stg_league_player_pt_shot": pl.DataFrame({"id": [5], "fga": [25]}).lazy(),
        }
        result = _run(FactLeaguePtShotsTransformer(), staging)
        assert result.shape[0] == 5
        assert "shot_type" in result.columns
        assert set(result["shot_type"].to_list()) == {
            "stats",
            "team_defend",
            "team",
            "opponent",
            "player",
        }


# ---------------------------------------------------------------------------
# 18. fact_game_context — LEFT JOINs on game_id
# ---------------------------------------------------------------------------
class TestFactGameContext:
    def test_class_attrs(self) -> None:
        assert FactGameContextTransformer.output_table == "fact_game_context"
        assert set(FactGameContextTransformer.depends_on) == {
            "stg_game_info",
            "stg_game_summary",
            "stg_other_stats",
            "stg_inactive_players",
            "stg_season_series",
            "stg_last_meeting",
            "stg_game_summary_available_video",
        }

    def test_union_with_context_source(self) -> None:
        staging = {
            "stg_game_summary": pl.DataFrame({"game_id": ["001"], "home_team_id": [1]}).lazy(),
            "stg_game_info": pl.DataFrame({"game_id": ["001"], "attendance": [18000]}).lazy(),
            "stg_other_stats": pl.DataFrame({"game_id": ["001"], "lead_changes": [12]}).lazy(),
            "stg_inactive_players": pl.DataFrame(
                {"game_id": ["002"], "player_id": [99]}
            ).lazy(),
            "stg_season_series": pl.DataFrame({"game_id": ["003"], "series_leader": [1]}).lazy(),
            "stg_last_meeting": pl.DataFrame({"game_id": ["004"], "winner": [2]}).lazy(),
            "stg_game_summary_available_video": pl.DataFrame(
                {"game_id": ["005"], "video_available": [1]}
            ).lazy(),
        }
        result = _run(FactGameContextTransformer(), staging)
        assert result.shape[0] == 5
        assert "context_source" in result.columns
        assert set(result["context_source"].to_list()) == {
            "summary",
            "inactive_players",
            "season_series",
            "last_meeting",
            "available_video",
        }


# ---------------------------------------------------------------------------
# 19. fact_season_matchups — UNION ALL BY NAME with matchup_type
# ---------------------------------------------------------------------------
class TestFactSeasonMatchups:
    def test_class_attrs(self) -> None:
        assert FactSeasonMatchupsTransformer.output_table == "fact_season_matchups"
        assert len(FactSeasonMatchupsTransformer.depends_on) == 2

    def test_union_with_matchup_type(self) -> None:
        staging = {
            "stg_season_matchups": pl.DataFrame({"matchup_id": [1], "team_id": [10]}).lazy(),
            "stg_matchups_rollup": pl.DataFrame({"matchup_id": [2], "team_id": [20]}).lazy(),
        }
        result = _run(FactSeasonMatchupsTransformer(), staging)
        assert result.shape[0] == 2
        assert "matchup_type" in result.columns
        assert set(result["matchup_type"].to_list()) == {"detail", "rollup"}


# ---------------------------------------------------------------------------
# 20. fact_fantasy — SELECT * passthrough
# ---------------------------------------------------------------------------
class TestFactFantasy:
    def test_class_attrs(self) -> None:
        assert FactFantasyTransformer.output_table == "fact_fantasy"
        assert set(FactFantasyTransformer.depends_on) == {
            "stg_fanduel_player",
            "stg_fantasy_widget",
            "stg_player_fantasy_profile_last_five_games_avg",
            "stg_player_fantasy_profile_season_avg",
        }

    def test_transform_union(self) -> None:
        staging = {
            "stg_fanduel_player": pl.DataFrame(
                {"player_id": [1], "fantasy_pts": [45.2], "salary": [8500]}
            ).lazy(),
            "stg_fantasy_widget": pl.DataFrame(
                {"player_id": [2], "fantasy_pts": [38.0], "salary": [7200]}
            ).lazy(),
            "stg_player_fantasy_profile_last_five_games_avg": pl.DataFrame(
                {"player_id": [3], "fantasy_pts": [26.1]}
            ).lazy(),
            "stg_player_fantasy_profile_season_avg": pl.DataFrame(
                {"player_id": [4], "fantasy_pts": [41.7]}
            ).lazy(),
        }
        result = _run(FactFantasyTransformer(), staging)
        assert result.shape[0] == 4
        assert "fantasy_source" in result.columns
        assert set(result["fantasy_source"].to_list()) == {
            "fanduel",
            "fantasy_widget",
            "player_fantasy_profile_last_five_games_avg",
            "player_fantasy_profile_season_avg",
        }


# ---------------------------------------------------------------------------
# 21. fact_cumulative_stats — UNION ALL BY NAME with entity_type + stat_type
# ---------------------------------------------------------------------------
class TestFactCumulativeStats:
    def test_class_attrs(self) -> None:
        assert FactCumulativeStatsTransformer.output_table == "fact_cumulative_stats"
        assert len(FactCumulativeStatsTransformer.depends_on) == 4

    def test_union_with_dual_discriminators(self) -> None:
        staging = {
            "stg_cume_player": pl.DataFrame({"id": [1], "pts": [100]}).lazy(),
            "stg_cume_player_games": pl.DataFrame({"id": [2], "gp": [50]}).lazy(),
            "stg_cume_team": pl.DataFrame({"id": [3], "pts": [5000]}).lazy(),
            "stg_cume_team_games": pl.DataFrame({"id": [4], "gp": [82]}).lazy(),
        }
        result = _run(FactCumulativeStatsTransformer(), staging)
        assert result.shape[0] == 4
        assert "entity_type" in result.columns
        assert "stat_type" in result.columns
        et = result["entity_type"].to_list()
        st = result["stat_type"].to_list()
        assert set(zip(et, st, strict=False)) == {
            ("player", "stats"),
            ("player", "games"),
            ("team", "stats"),
            ("team", "games"),
        }


# ---------------------------------------------------------------------------
# 22. fact_team_matchups — UNION ALL BY NAME with matchup_type (3 tables)
# ---------------------------------------------------------------------------
class TestFactTeamMatchups:
    def test_class_attrs(self) -> None:
        assert FactTeamMatchupsTransformer.output_table == "fact_team_matchups"
        assert len(FactTeamMatchupsTransformer.depends_on) == 3

    def test_union_with_matchup_type(self) -> None:
        staging = {
            "stg_team_vs_player": pl.DataFrame({"id": [1], "team_id": [10]}).lazy(),
            "stg_team_and_players_vs": pl.DataFrame({"id": [2], "team_id": [20]}).lazy(),
            "stg_team_and_players_vs_players": pl.DataFrame({"id": [3], "team_id": [30]}).lazy(),
        }
        result = _run(FactTeamMatchupsTransformer(), staging)
        assert result.shape[0] == 3
        assert "matchup_type" in result.columns
        assert set(result["matchup_type"].to_list()) == {
            "team_vs_player",
            "team_and_players_vs",
            "team_and_players_vs_players",
        }


# ---------------------------------------------------------------------------
# 23. fact_player_matchups — UNION ALL BY NAME with matchup_type
# ---------------------------------------------------------------------------
class TestFactPlayerMatchups:
    def test_class_attrs(self) -> None:
        assert FactPlayerMatchupsTransformer.output_table == "fact_player_matchups"
        assert len(FactPlayerMatchupsTransformer.depends_on) == 2

    def test_union_with_matchup_type(self) -> None:
        staging = {
            "stg_player_vs_player": pl.DataFrame({"player_id": [1], "opp_id": [2]}).lazy(),
            "stg_player_compare": pl.DataFrame({"player_id": [3], "opp_id": [4]}).lazy(),
        }
        result = _run(FactPlayerMatchupsTransformer(), staging)
        assert result.shape[0] == 2
        assert "matchup_type" in result.columns
        assert set(result["matchup_type"].to_list()) == {"head_to_head", "compare"}


# ---------------------------------------------------------------------------
# 24. fact_streak_finder — UNION ALL BY NAME with entity_type (3 tables)
# ---------------------------------------------------------------------------
class TestFactStreakFinder:
    def test_class_attrs(self) -> None:
        assert FactStreakFinderTransformer.output_table == "fact_streak_finder"
        assert len(FactStreakFinderTransformer.depends_on) == 3

    def test_union_with_entity_type(self) -> None:
        staging = {
            "stg_player_streak_finder": pl.DataFrame({"id": [1], "streak": [10]}).lazy(),
            "stg_player_game_streak_finder": pl.DataFrame({"id": [2], "streak": [5]}).lazy(),
            "stg_team_streak_finder": pl.DataFrame({"id": [3], "streak": [12]}).lazy(),
        }
        result = _run(FactStreakFinderTransformer(), staging)
        assert result.shape[0] == 3
        assert "entity_type" in result.columns
        assert set(result["entity_type"].to_list()) == {
            "player",
            "player_game",
            "team",
        }
