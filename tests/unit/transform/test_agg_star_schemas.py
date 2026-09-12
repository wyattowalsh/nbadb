"""Tests for all agg_* Pandera star-schema contracts."""

from __future__ import annotations

import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.transform.pipeline import _star_schema_map

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGG_TABLES = [
    "agg_all_time_leaders",
    "agg_clutch_stats",
    "agg_game_totals",
    "agg_league_leaders",
    "agg_lineup_efficiency",
    "agg_player_bio",
    "agg_player_career",
    "agg_player_rolling",
    "agg_player_season",
    "agg_player_season_per36",
    "agg_player_season_advanced",
    "agg_player_season_per48",
    "agg_shot_location_season",
    "agg_shot_zones",
    "agg_team_defense",
    "agg_team_franchise",
    "agg_team_pace_and_efficiency",
    "agg_team_season",
]


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({k: [v] for k, v in values.items()})


def _validate(table: str, row: dict[str, object]) -> pl.DataFrame:
    schema_cls = _star_schema_map()[table]
    return schema_cls.validate(_frame(row))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_all_agg_schemas_are_discovered() -> None:
    discovered = set(_star_schema_map().keys())
    missing = [t for t in _AGG_TABLES if t not in discovered]
    assert not missing, f"Missing from _star_schema_map: {missing}"


# ---------------------------------------------------------------------------
# Per-schema validation
# ---------------------------------------------------------------------------


class TestAggAllTimeLeadersSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_all_time_leaders",
            {
                "player_id": 2544,
                "player_name": "LeBron James",
                "pts": 40000,
                "ast": 11000,
                "reb": 11500,
                "pts_rank": 1,
                "ast_rank": 2,
                "reb_rank": 3,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_stats(self) -> None:
        result = _validate(
            "agg_all_time_leaders",
            {
                "player_id": 201935,
                "player_name": None,
                "pts": None,
                "ast": None,
                "reb": None,
                "pts_rank": None,
                "ast_rank": None,
                "reb_rank": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggClutchStatsSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_clutch_stats",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "clutch_gp": 30,
                "clutch_min": 45.5,
                "clutch_pts": 62.0,
                "clutch_fg_pct": 0.48,
                "clutch_ft_pct": 0.72,
                "league_clutch_pts": 55.0,
                "league_clutch_fg_pct": 0.44,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "agg_clutch_stats",
            {
                "player_id": None,
                "season_year": None,
                "clutch_gp": None,
                "clutch_min": None,
                "clutch_pts": None,
                "clutch_fg_pct": None,
                "clutch_ft_pct": None,
                "league_clutch_pts": None,
                "league_clutch_fg_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggGameTotalsSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_game_totals",
            {
                "game_id": 1001,
                "game_date": "2024-01-15",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "home_team_id": 10,
                "away_team_id": 20,
                "home_pts": 110,
                "away_pts": 102,
                "total_pts": 212,
                "home_reb": 40,
                "away_reb": 38,
                "home_ast": 25,
                "away_ast": 22,
                "home_fg_pct": 0.471,
                "away_fg_pct": 0.438,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_stat_fields(self) -> None:
        result = _validate(
            "agg_game_totals",
            {
                "game_id": 1001,
                "game_date": "2024-01-15",
                "season_year": "2024-25",
                "season_type": None,
                "home_team_id": 10,
                "away_team_id": 20,
                "home_pts": None,
                "away_pts": None,
                "total_pts": None,
                "home_reb": None,
                "away_reb": None,
                "home_ast": None,
                "away_ast": None,
                "home_fg_pct": None,
                "away_fg_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggLeagueLeadersSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_league_leaders",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "avg_pts": 25.7,
                "avg_reb": 7.3,
                "avg_ast": 8.3,
                "avg_stl": 1.3,
                "avg_blk": 0.6,
                "fg_pct": 0.540,
                "fg3_pct": 0.410,
                "ft_pct": 0.745,
                "pts_rank": 1,
                "reb_rank": 12,
                "ast_rank": 3,
                "stl_rank": 8,
                "blk_rank": 25,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggLineupEfficiencySchema:
    _COVERAGE_FIELDS = (
        "gp_covered_observations",
        "minutes_covered_observations",
        "estimated_possessions_covered_observations",
        "win_pct_covered_observations",
        "fg_pct_covered_observations",
        "fg3_pct_covered_observations",
        "ft_pct_covered_observations",
        "efg_pct_covered_observations",
        "ts_pct_covered_observations",
        "fg3a_per_fga_covered_observations",
        "fta_per_fga_covered_observations",
        "ast_tov_ratio_covered_observations",
        "pts_per48_covered_observations",
        "reb_per48_covered_observations",
        "ast_per48_covered_observations",
        "tov_per48_covered_observations",
        "stl_per48_covered_observations",
        "blk_per48_covered_observations",
        "plus_minus_per48_covered_observations",
        "estimated_off_rating_covered_observations",
        "estimated_def_rating_covered_observations",
        "estimated_net_rating_covered_observations",
    )
    _TOTAL_FIELDS = (
        "total_gp",
        "total_w",
        "total_l",
        "total_min",
        "total_fgm",
        "total_fga",
        "total_fg3m",
        "total_fg3a",
        "total_ftm",
        "total_fta",
        "total_oreb",
        "total_dreb",
        "total_reb",
        "total_ast",
        "total_tov",
        "total_stl",
        "total_blk",
        "total_blka",
        "total_pf",
        "total_pfd",
        "total_pts",
        "total_plus_minus",
    )
    _METRIC_FIELDS = (
        "win_pct",
        "fg_pct",
        "fg3_pct",
        "ft_pct",
        "efg_pct",
        "ts_pct",
        "fg3a_per_fga",
        "fta_per_fga",
        "ast_tov_ratio",
        "estimated_possessions",
        "pts_per48",
        "reb_per48",
        "ast_per48",
        "tov_per48",
        "stl_per48",
        "blk_per48",
        "plus_minus_per48",
        "estimated_off_rating",
        "estimated_def_rating",
        "estimated_net_rating",
    )

    @classmethod
    def _row(cls, *, covered: bool) -> dict[str, object]:
        row: dict[str, object] = {
            "group_id": "1-2-3-4-5",
            "team_id": 1610612738,
            "season_year": "2024-25",
            "season_type": "Regular Season",
            "lineup_source": "league",
            "lineup_source_count": 1,
            "lineup_source_coverage": "league",
            "canonical_observation_count": 1,
            **{field: int(covered) for field in cls._COVERAGE_FIELDS},
            **{field: (1 if covered else None) for field in cls._TOTAL_FIELDS},
            **{field: (1.0 if covered else None) for field in cls._METRIC_FIELDS},
        }
        return row

    def test_valid_row(self) -> None:
        assert isinstance(
            _validate("agg_lineup_efficiency", self._row(covered=True)),
            pl.DataFrame,
        )

    def test_nullable_stats_have_zero_metric_local_coverage(self) -> None:
        row = self._row(covered=False)
        row.update(
            lineup_source="team",
            lineup_source_count=1,
            lineup_source_coverage="team",
        )

        assert isinstance(_validate("agg_lineup_efficiency", row), pl.DataFrame)


class TestAggPlayerBioSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_bio",
            {
                "player_id": 2544,
                "player_name": "LeBron James",
                "team_id": 1610612747,
                "team_abbreviation": "LAL",
                "age": 39.0,
                "player_height": "6-9",
                "player_height_inches": 81.0,
                "player_weight": 250.0,
                "college": None,
                "country": "USA",
                "draft_year": "2003",
                "draft_round": "1",
                "draft_number": "1",
                "gp": 71,
                "pts": 25.7,
                "reb": 7.3,
                "ast": 8.3,
                "net_rating": 5.2,
                "oreb_pct": 0.05,
                "dreb_pct": 0.19,
                "usg_pct": 0.29,
                "ts_pct": 0.621,
                "ast_pct": 0.43,
                "season_year": "2024-25",
                "season_type": "Regular Season",
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerCareerSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_career",
            {
                "player_id": 2544,
                "career_gp": 1487,
                "career_min": 55000.0,
                "career_pts": 42000.0,
                "career_ppg": 27.2,
                "career_rpg": 7.5,
                "career_apg": 7.4,
                "career_spg": 1.6,
                "career_bpg": 0.7,
                "career_fg_pct": 0.504,
                "career_fg3_pct": 0.345,
                "career_ft_pct": 0.734,
                "first_season": "2003-04",
                "last_season": "2024-25",
                "seasons_played": 22,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_pct_fields(self) -> None:
        result = _validate(
            "agg_player_career",
            {
                "player_id": 9999,
                "career_gp": 0,
                "career_min": 0.0,
                "career_pts": 0.0,
                "career_ppg": None,
                "career_rpg": None,
                "career_apg": None,
                "career_spg": None,
                "career_bpg": None,
                "career_fg_pct": None,
                "career_fg3_pct": None,
                "career_ft_pct": None,
                "first_season": None,
                "last_season": None,
                "seasons_played": 0,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerRollingSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_rolling",
            {
                "game_id": "0022401000",
                "player_id": 2544,
                "game_date": "2025-01-15",
                "pts_roll5": 27.6,
                "reb_roll5": 8.0,
                "ast_roll5": 9.2,
                "pts_roll10": 26.3,
                "reb_roll10": 7.5,
                "ast_roll10": 8.8,
                "pts_roll20": 25.9,
                "reb_roll20": 7.4,
                "ast_roll20": 8.4,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_rolling_windows(self) -> None:
        result = _validate(
            "agg_player_rolling",
            {
                "game_id": "0022400001",
                "player_id": 1630162,
                "game_date": "2024-10-22",
                "pts_roll5": None,
                "reb_roll5": None,
                "ast_roll5": None,
                "pts_roll10": None,
                "reb_roll10": None,
                "ast_roll10": None,
                "pts_roll20": None,
                "reb_roll20": None,
                "ast_roll20": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerSeasonSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_season",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "team_abbreviation": "LAL",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "minutes_covered_games": 71,
                "scoring_covered_games": 71,
                "rebounding_covered_games": 71,
                "playmaking_covered_games": 71,
                "shooting_covered_games": 71,
                "advanced_covered_games": 70,
                "advanced_possessions": 5100.0,
                "total_min": 2400.0,
                "avg_min": 33.8,
                "total_pts": 1825.0,
                "avg_pts": 25.7,
                "total_reb": 518.0,
                "avg_reb": 7.3,
                "total_ast": 590.0,
                "avg_ast": 8.3,
                "total_stl": 92.0,
                "avg_stl": 1.3,
                "total_blk": 43.0,
                "avg_blk": 0.6,
                "total_tov": 254.0,
                "avg_tov": 3.6,
                "total_oreb": 80.0,
                "total_dreb": 438.0,
                "total_pf": 120.0,
                "total_plus_minus": 320.0,
                "total_fgm": 680.0,
                "total_fga": 1258.0,
                "fg_pct": 0.540,
                "total_fg3m": 182.0,
                "total_fg3a": 444.0,
                "fg3_pct": 0.410,
                "total_ftm": 283.0,
                "total_fta": 380.0,
                "ft_pct": 0.745,
                "efg_pct": 0.613,
                "three_point_attempt_rate": 0.353,
                "free_throw_attempt_rate": 0.302,
                "ast_tov_ratio": 2.323,
                "rating_covered_games": 70,
                "rating_possessions": 5100.0,
                "avg_off_rating": 121.3,
                "avg_def_rating": 110.5,
                "avg_net_rating": 10.8,
                "avg_ts_pct": 0.621,
                "provider_ts_covered_games": 70,
                "provider_ts_possessions": 5100.0,
                "provider_avg_ts_pct": 0.619,
                "usage_covered_games": 70,
                "usage_possessions": 5100.0,
                "avg_usg_pct": 0.290,
                "pie_covered_games": 70,
                "pie_possessions": 5100.0,
                "avg_pie": 0.168,
                "shooting_efficiency_source": "derived_traditional_totals",
                "advanced_metric_weight": "provider_possessions",
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerSeasonPer36Schema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_season_per36",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "avg_min": 33.8,
                "pts_per36": 27.4,
                "reb_per36": 7.8,
                "ast_per36": 8.8,
                "stl_per36": 1.4,
                "blk_per36": 0.6,
                "tov_per36": 3.8,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_null_rates_when_no_minutes(self) -> None:
        result = _validate(
            "agg_player_season_per36",
            {
                "player_id": 9999,
                "team_id": 1610612750,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 1,
                "avg_min": None,
                "pts_per36": None,
                "reb_per36": None,
                "ast_per36": None,
                "stl_per36": None,
                "blk_per36": None,
                "tov_per36": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerSeasonPer48Schema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_season_per48",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "avg_min": 33.8,
                "pts_per48": 36.5,
                "reb_per48": 10.4,
                "ast_per48": 11.8,
                "stl_per48": 1.8,
                "blk_per48": 0.9,
                "tov_per48": 5.1,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggPlayerSeasonAdvancedSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_player_season_advanced",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "minutes_covered_games": 71,
                "total_min": 2400.0,
                "possession_covered_games": 71,
                "total_possessions": 5200.0,
                "pace_covered_games": 71,
                "pace_covered_minutes": 2400.0,
                "off_rating_covered_games": 71,
                "off_rating_covered_possessions": 5200.0,
                "avg_off_rating": 121.3,
                "def_rating_covered_games": 71,
                "def_rating_covered_possessions": 5200.0,
                "avg_def_rating": 110.5,
                "net_rating_covered_games": 71,
                "net_rating_covered_possessions": 5200.0,
                "avg_net_rating": 10.8,
                "ts_pct_covered_games": 71,
                "ts_pct_covered_possessions": 5200.0,
                "avg_ts_pct": 0.621,
                "usg_pct_covered_games": 71,
                "usg_pct_covered_possessions": 5200.0,
                "avg_usg_pct": 0.290,
                "efg_pct_covered_games": 71,
                "efg_pct_covered_possessions": 5200.0,
                "avg_efg_pct": 0.575,
                "ast_pct_covered_games": 71,
                "ast_pct_covered_possessions": 5200.0,
                "avg_ast_pct": 0.430,
                "ast_ratio_covered_games": 71,
                "ast_ratio_covered_possessions": 5200.0,
                "avg_ast_ratio": 0.350,
                "oreb_pct_covered_games": 71,
                "oreb_pct_covered_possessions": 5200.0,
                "avg_oreb_pct": 0.050,
                "dreb_pct_covered_games": 71,
                "dreb_pct_covered_possessions": 5200.0,
                "avg_dreb_pct": 0.190,
                "reb_pct_covered_games": 71,
                "reb_pct_covered_possessions": 5200.0,
                "avg_reb_pct": 0.120,
                "tov_pct_covered_games": 71,
                "tov_pct_covered_possessions": 5200.0,
                "avg_tov_pct": 0.130,
                "avg_pace": 99.5,
                "pie_covered_games": 71,
                "pie_covered_possessions": 5200.0,
                "avg_pie": 0.168,
                "advanced_metric_source": "provider_possession_weighted",
                "pace_source": "provider_minute_weighted",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "agg_player_season_advanced",
            {
                "player_id": 201935,
                "team_id": 1610612745,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 0,
                "minutes_covered_games": 0,
                "total_min": None,
                "possession_covered_games": 0,
                "total_possessions": None,
                "pace_covered_games": 0,
                "pace_covered_minutes": None,
                "off_rating_covered_games": 0,
                "off_rating_covered_possessions": None,
                "avg_off_rating": None,
                "def_rating_covered_games": 0,
                "def_rating_covered_possessions": None,
                "avg_def_rating": None,
                "net_rating_covered_games": 0,
                "net_rating_covered_possessions": None,
                "avg_net_rating": None,
                "ts_pct_covered_games": 0,
                "ts_pct_covered_possessions": None,
                "avg_ts_pct": None,
                "usg_pct_covered_games": 0,
                "usg_pct_covered_possessions": None,
                "avg_usg_pct": None,
                "efg_pct_covered_games": 0,
                "efg_pct_covered_possessions": None,
                "avg_efg_pct": None,
                "ast_pct_covered_games": 0,
                "ast_pct_covered_possessions": None,
                "avg_ast_pct": None,
                "ast_ratio_covered_games": 0,
                "ast_ratio_covered_possessions": None,
                "avg_ast_ratio": None,
                "oreb_pct_covered_games": 0,
                "oreb_pct_covered_possessions": None,
                "avg_oreb_pct": None,
                "dreb_pct_covered_games": 0,
                "dreb_pct_covered_possessions": None,
                "avg_dreb_pct": None,
                "reb_pct_covered_games": 0,
                "reb_pct_covered_possessions": None,
                "avg_reb_pct": None,
                "tov_pct_covered_games": 0,
                "tov_pct_covered_possessions": None,
                "avg_tov_pct": None,
                "avg_pace": None,
                "pie_covered_games": 0,
                "pie_covered_possessions": None,
                "avg_pie": None,
                "advanced_metric_source": "provider_possession_weighted",
                "pace_source": "provider_minute_weighted",
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggShotLocationSeasonSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_shot_location_season",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "fgm": 680,
                "season_fgm_rank": 1,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_null_fgm(self) -> None:
        result = _validate(
            "agg_shot_location_season",
            {
                "player_id": 9999,
                "season_year": "2024-25",
                "fgm": None,
                "season_fgm_rank": 450,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggShotZonesSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_shot_zones",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "shot_zone_basic": "Mid-Range",
                "shot_zone_area": "Center(C)",
                "shot_zone_range": "16-24 ft.",
                "shot_event_count": 120,
                "outcome_observed_attempt_count": 119,
                "made_shot_count_of_observed_outcomes": 55,
                "fg_pct_of_observed_outcomes": 0.462,
                "distance_observed_attempt_count": 118,
                "mean_observed_shot_distance": 18.3,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_unobserved_metrics_remain_null(self) -> None:
        result = _validate(
            "agg_shot_zones",
            {
                "player_id": 201935,
                "season_year": "2023-24",
                "season_type": "Playoffs",
                "shot_zone_basic": "Restricted Area",
                "shot_zone_area": "Center(C)",
                "shot_zone_range": "Less Than 8 ft.",
                "shot_event_count": 2,
                "outcome_observed_attempt_count": 0,
                "made_shot_count_of_observed_outcomes": 0,
                "fg_pct_of_observed_outcomes": None,
                "distance_observed_attempt_count": 0,
                "mean_observed_shot_distance": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


def _team_defense_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "team_id": 1610612738,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "observed_game_count": 3,
        "def_rating_coverage_game_count": 2,
        "mean_observed_game_def_rating": 107.5,
        "net_rating_coverage_game_count": 2,
        "mean_observed_game_net_rating": 4.2,
        "four_factors_observed_game_count": 2,
        "opp_effective_field_goal_percentage_coverage_game_count": 2,
        "mean_observed_game_opp_effective_field_goal_percentage": 0.505,
        "opp_free_throw_attempt_rate_coverage_game_count": 2,
        "mean_observed_game_opp_free_throw_attempt_rate": 0.242,
        "opp_team_turnover_percentage_coverage_game_count": 1,
        "mean_observed_game_opp_team_turnover_percentage": 0.138,
        "opp_offensive_rebound_percentage_coverage_game_count": 1,
        "mean_observed_game_opp_offensive_rebound_percentage": 0.260,
        "hustle_observed_game_count": 2,
        "contested_shots_coverage_game_count": 2,
        "total_observed_game_contested_shots": 90.6,
        "mean_observed_game_contested_shots": 45.3,
        "deflections_coverage_game_count": 2,
        "total_observed_game_deflections": 25.6,
        "mean_observed_game_deflections": 12.8,
        "loose_balls_recovered_coverage_game_count": 2,
        "total_observed_game_loose_balls_recovered": 14.2,
        "mean_observed_game_loose_balls_recovered": 7.1,
        "charges_drawn_coverage_game_count": 2,
        "total_observed_game_charges_drawn": 3.8,
        "mean_observed_game_charges_drawn": 1.9,
        "screen_assists_coverage_game_count": 2,
        "total_observed_game_screen_assists": 18.8,
        "mean_observed_game_screen_assists": 9.4,
    }
    row.update(updates)
    return row


_TEAM_DEFENSE_MEAN_COVERAGE_BINDINGS = (
    ("def_rating_coverage_game_count", "mean_observed_game_def_rating"),
    ("net_rating_coverage_game_count", "mean_observed_game_net_rating"),
    (
        "opp_effective_field_goal_percentage_coverage_game_count",
        "mean_observed_game_opp_effective_field_goal_percentage",
    ),
    (
        "opp_free_throw_attempt_rate_coverage_game_count",
        "mean_observed_game_opp_free_throw_attempt_rate",
    ),
    (
        "opp_team_turnover_percentage_coverage_game_count",
        "mean_observed_game_opp_team_turnover_percentage",
    ),
    (
        "opp_offensive_rebound_percentage_coverage_game_count",
        "mean_observed_game_opp_offensive_rebound_percentage",
    ),
)

_TEAM_DEFENSE_HUSTLE_COVERAGE_BINDINGS = (
    (
        "contested_shots_coverage_game_count",
        "total_observed_game_contested_shots",
        "mean_observed_game_contested_shots",
    ),
    (
        "deflections_coverage_game_count",
        "total_observed_game_deflections",
        "mean_observed_game_deflections",
    ),
    (
        "loose_balls_recovered_coverage_game_count",
        "total_observed_game_loose_balls_recovered",
        "mean_observed_game_loose_balls_recovered",
    ),
    (
        "charges_drawn_coverage_game_count",
        "total_observed_game_charges_drawn",
        "mean_observed_game_charges_drawn",
    ),
    (
        "screen_assists_coverage_game_count",
        "total_observed_game_screen_assists",
        "mean_observed_game_screen_assists",
    ),
)


class TestAggTeamDefenseSchema:
    def test_valid_row(self) -> None:
        result = _validate("agg_team_defense", _team_defense_row())

        assert isinstance(result, pl.DataFrame)

    def test_absent_optional_sources_keep_nullable_measures_unknown(self) -> None:
        result = _validate(
            "agg_team_defense",
            _team_defense_row(
                team_id=1610612762,
                season_year="2015-16",
                season_type="Playoffs",
                observed_game_count=5,
                def_rating_coverage_game_count=5,
                mean_observed_game_def_rating=108.0,
                net_rating_coverage_game_count=0,
                mean_observed_game_net_rating=None,
                four_factors_observed_game_count=0,
                opp_effective_field_goal_percentage_coverage_game_count=0,
                mean_observed_game_opp_effective_field_goal_percentage=None,
                opp_free_throw_attempt_rate_coverage_game_count=0,
                mean_observed_game_opp_free_throw_attempt_rate=None,
                opp_team_turnover_percentage_coverage_game_count=0,
                mean_observed_game_opp_team_turnover_percentage=None,
                opp_offensive_rebound_percentage_coverage_game_count=0,
                mean_observed_game_opp_offensive_rebound_percentage=None,
                hustle_observed_game_count=0,
                contested_shots_coverage_game_count=0,
                total_observed_game_contested_shots=None,
                mean_observed_game_contested_shots=None,
                deflections_coverage_game_count=0,
                total_observed_game_deflections=None,
                mean_observed_game_deflections=None,
                loose_balls_recovered_coverage_game_count=0,
                total_observed_game_loose_balls_recovered=None,
                mean_observed_game_loose_balls_recovered=None,
                charges_drawn_coverage_game_count=0,
                total_observed_game_charges_drawn=None,
                mean_observed_game_charges_drawn=None,
                screen_assists_coverage_game_count=0,
                total_observed_game_screen_assists=None,
                mean_observed_game_screen_assists=None,
            ),
        )

        assert isinstance(result, pl.DataFrame)

    def test_coverage_count_cannot_exceed_source_denominator(self) -> None:
        with pytest.raises(SchemaError, match="coverage_counts_do_not_exceed_denominators"):
            _validate(
                "agg_team_defense",
                _team_defense_row(
                    hustle_observed_game_count=1,
                    contested_shots_coverage_game_count=2,
                ),
            )

    @pytest.mark.parametrize(
        ("coverage_count", "mean_value", "is_valid"),
        [
            pytest.param(0, None, True, id="zero-null"),
            pytest.param(0, 1.0, False, id="zero-nonnull"),
            pytest.param(1, None, False, id="positive-null"),
            pytest.param(1, 1.0, True, id="positive-nonnull"),
        ],
    )
    @pytest.mark.parametrize(
        ("coverage_column", "mean_column"),
        _TEAM_DEFENSE_MEAN_COVERAGE_BINDINGS,
        ids=[item[0] for item in _TEAM_DEFENSE_MEAN_COVERAGE_BINDINGS],
    )
    def test_mean_nullability_matches_exact_metric_coverage(
        self,
        coverage_column: str,
        mean_column: str,
        coverage_count: int,
        mean_value: float | None,
        is_valid: bool,
    ) -> None:
        row = _team_defense_row(
            **{
                coverage_column: coverage_count,
                mean_column: mean_value,
            }
        )

        if is_valid:
            assert isinstance(_validate("agg_team_defense", row), pl.DataFrame)
            return
        with pytest.raises(SchemaError, match="aggregate_nullability_matches_coverage"):
            _validate("agg_team_defense", row)

    @pytest.mark.parametrize(
        ("coverage_count", "total_value", "mean_value", "is_valid"),
        [
            pytest.param(0, None, None, True, id="zero-null-null"),
            pytest.param(0, None, 1.0, False, id="zero-null-nonnull"),
            pytest.param(0, 1.0, None, False, id="zero-nonnull-null"),
            pytest.param(0, 1.0, 1.0, False, id="zero-nonnull-nonnull"),
            pytest.param(1, None, None, False, id="positive-null-null"),
            pytest.param(1, None, 1.0, False, id="positive-null-nonnull"),
            pytest.param(1, 1.0, None, False, id="positive-nonnull-null"),
            pytest.param(1, 1.0, 1.0, True, id="positive-nonnull-nonnull"),
        ],
    )
    @pytest.mark.parametrize(
        ("coverage_column", "total_column", "mean_column"),
        _TEAM_DEFENSE_HUSTLE_COVERAGE_BINDINGS,
        ids=[item[0] for item in _TEAM_DEFENSE_HUSTLE_COVERAGE_BINDINGS],
    )
    def test_hustle_total_and_mean_nullability_match_exact_metric_coverage(
        self,
        coverage_column: str,
        total_column: str,
        mean_column: str,
        coverage_count: int,
        total_value: float | None,
        mean_value: float | None,
        is_valid: bool,
    ) -> None:
        row = _team_defense_row(
            **{
                coverage_column: coverage_count,
                total_column: total_value,
                mean_column: mean_value,
            }
        )

        if is_valid:
            assert isinstance(_validate("agg_team_defense", row), pl.DataFrame)
            return
        with pytest.raises(SchemaError, match="aggregate_nullability_matches_coverage"):
            _validate("agg_team_defense", row)


class TestAggTeamFranchiseSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_team_franchise",
            {
                "team_id": 1610612738,
                "team_city": "Boston",
                "team_name": "Celtics",
                "start_year": 1946,
                "end_year": 2025,
                "years": 79,
                "games": 6000,
                "wins": 3500,
                "losses": 2500,
                "win_pct": 0.583,
                "po_appearances": 52,
                "div_titles": 30,
                "conf_titles": 22,
                "league_titles": 18,
                "franchise_age_years": 80,
                "computed_win_pct": 0.583,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_stats(self) -> None:
        result = _validate(
            "agg_team_franchise",
            {
                "team_id": 1610612762,
                "team_city": None,
                "team_name": None,
                "start_year": None,
                "end_year": None,
                "years": None,
                "games": None,
                "wins": None,
                "losses": None,
                "win_pct": None,
                "po_appearances": None,
                "div_titles": None,
                "conf_titles": None,
                "league_titles": None,
                "franchise_age_years": None,
                "computed_win_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggTeamPaceAndEfficiencySchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_team_pace_and_efficiency",
            {
                "team_id": 1610612738,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 82,
                "total_possessions": 8088.0,
                "rating_covered_games": 81,
                "rating_possessions": 7990.0,
                "pace_covered_games": 82,
                "pace_actual_minutes_games": 80,
                "pace_inferred_minutes_games": 2,
                "pace_covered_minutes": 3945.0,
                "avg_pace": 98.4,
                "avg_ortg": 121.8,
                "avg_drtg": 110.5,
                "avg_net_rtg": 11.3,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_ratings(self) -> None:
        result = _validate(
            "agg_team_pace_and_efficiency",
            {
                "team_id": 1610612750,
                "season_year": "2024-25",
                "season_type": "Playoffs",
                "gp": 6,
                "total_possessions": None,
                "rating_covered_games": 0,
                "rating_possessions": None,
                "pace_covered_games": 0,
                "pace_actual_minutes_games": 0,
                "pace_inferred_minutes_games": 0,
                "pace_covered_minutes": None,
                "avg_pace": None,
                "avg_ortg": None,
                "avg_drtg": None,
                "avg_net_rtg": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAggTeamSeasonSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "agg_team_season",
            {
                "team_id": 1610612738,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 82,
                "avg_pts": 118.7,
                "avg_reb": 44.4,
                "avg_ast": 27.1,
                "avg_stl": 7.9,
                "avg_blk": 5.3,
                "avg_tov": 12.8,
                "fg_pct": 0.485,
                "fg3_pct": 0.374,
                "ft_pct": 0.778,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_pct_fields(self) -> None:
        result = _validate(
            "agg_team_season",
            {
                "team_id": 1610612762,
                "season_year": "1946-47",
                "season_type": "Regular Season",
                "gp": 60,
                "avg_pts": None,
                "avg_reb": None,
                "avg_ast": None,
                "avg_stl": None,
                "avg_blk": None,
                "avg_tov": None,
                "fg_pct": None,
                "fg3_pct": None,
                "ft_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table,bad_row,description",
    [
        (
            "agg_all_time_leaders",
            {
                "player_id": -1,
                "player_name": "Bad",
                "pts": 100,
                "ast": 50,
                "reb": 60,
                "pts_rank": 1,
                "ast_rank": 1,
                "reb_rank": 1,
            },
            "player_id must be > 0",
        ),
        (
            "agg_team_season",
            {
                "team_id": 0,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 82,
                "avg_pts": None,
                "avg_reb": None,
                "avg_ast": None,
                "avg_stl": None,
                "avg_blk": None,
                "avg_tov": None,
                "fg_pct": None,
                "fg3_pct": None,
                "ft_pct": None,
            },
            "team_id must be > 0",
        ),
        (
            "agg_team_defense",
            _team_defense_row(team_id=0),
            "agg_team_defense team_id must be > 0",
        ),
        (
            "agg_league_leaders",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "avg_pts": 25.7,
                "avg_reb": 7.3,
                "avg_ast": 8.3,
                "avg_stl": 1.3,
                "avg_blk": 0.6,
                "fg_pct": 0.540,
                "fg3_pct": 0.410,
                "ft_pct": 0.745,
                "pts_rank": 0,
                "reb_rank": 1,
                "ast_rank": 1,
                "stl_rank": 1,
                "blk_rank": 1,
            },
            "pts_rank must be >= 1",
        ),
        (
            "agg_player_season_advanced",
            {
                "player_id": -1,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "gp": 71,
                "minutes_covered_games": 0,
                "total_min": None,
                "possession_covered_games": 0,
                "total_possessions": None,
                "pace_covered_games": 0,
                "pace_covered_minutes": None,
                "off_rating_covered_games": 0,
                "off_rating_covered_possessions": None,
                "avg_off_rating": None,
                "def_rating_covered_games": 0,
                "def_rating_covered_possessions": None,
                "avg_def_rating": None,
                "net_rating_covered_games": 0,
                "net_rating_covered_possessions": None,
                "avg_net_rating": None,
                "ts_pct_covered_games": 0,
                "ts_pct_covered_possessions": None,
                "avg_ts_pct": None,
                "usg_pct_covered_games": 0,
                "usg_pct_covered_possessions": None,
                "avg_usg_pct": None,
                "efg_pct_covered_games": 0,
                "efg_pct_covered_possessions": None,
                "avg_efg_pct": None,
                "ast_pct_covered_games": 0,
                "ast_pct_covered_possessions": None,
                "avg_ast_pct": None,
                "ast_ratio_covered_games": 0,
                "ast_ratio_covered_possessions": None,
                "avg_ast_ratio": None,
                "oreb_pct_covered_games": 0,
                "oreb_pct_covered_possessions": None,
                "avg_oreb_pct": None,
                "dreb_pct_covered_games": 0,
                "dreb_pct_covered_possessions": None,
                "avg_dreb_pct": None,
                "reb_pct_covered_games": 0,
                "reb_pct_covered_possessions": None,
                "avg_reb_pct": None,
                "tov_pct_covered_games": 0,
                "tov_pct_covered_possessions": None,
                "avg_tov_pct": None,
                "avg_pace": None,
                "pie_covered_games": 0,
                "pie_covered_possessions": None,
                "avg_pie": None,
                "advanced_metric_source": "provider_possession_weighted",
                "pace_source": "provider_minute_weighted",
            },
            "agg_player_season_advanced player_id must be > 0",
        ),
        (
            "agg_game_totals",
            {
                "game_id": "",
                "game_date": "2024-01-15",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "home_team_id": 10,
                "away_team_id": 20,
                "home_pts": 110,
                "away_pts": 102,
                "total_pts": 212,
                "home_reb": 40,
                "away_reb": 38,
                "home_ast": 25,
                "away_ast": 22,
                "home_fg_pct": 0.471,
                "away_fg_pct": 0.438,
            },
            "game_id must be nonblank",
        ),
    ],
)
def test_schema_rejects_invalid_data(
    table: str, bad_row: dict[str, object], description: str
) -> None:
    import pandera.errors

    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        _validate(table, bad_row)
