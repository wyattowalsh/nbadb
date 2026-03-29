"""Tests for all analytics_* Pandera star-schema contracts."""

from __future__ import annotations

import polars as pl
import pytest

from nbadb.transform.pipeline import _star_schema_map

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANALYTICS_TABLES = [
    "analytics_clutch_performance",
    "analytics_draft_value",
    "analytics_game_summary",
    "analytics_head_to_head",
    "analytics_league_benchmarks",
    "analytics_player_game_complete",
    "analytics_player_impact",
    "analytics_player_matchup",
    "analytics_player_season_complete",
    "analytics_shooting_efficiency",
    "analytics_team_game_complete",
    "analytics_team_season_summary",
]


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({k: [v] for k, v in values.items()})


def _validate(table: str, row: dict[str, object]) -> pl.DataFrame:
    schema_cls = _star_schema_map()[table]
    return schema_cls.validate(_frame(row))


def _positive_int_id_fields(table: str) -> list[str]:
    schema = _star_schema_map()[table].to_schema()
    return [
        name
        for name, column in schema.columns.items()
        if (name == "person_id" or name.endswith("_id")) and str(column.dtype).startswith("Int")
    ]


def _synthetic_valid_row(table: str) -> dict[str, object]:
    schema = _star_schema_map()[table].to_schema()
    row: dict[str, object] = {}
    for name, column in schema.columns.items():
        dtype_name = str(column.dtype)
        if dtype_name.startswith("Int"):
            row[name] = 1
        elif dtype_name.startswith("Float"):
            row[name] = 1.0
        elif dtype_name == "String":
            row[name] = f"{name}-value"
        else:  # pragma: no cover - guards future dtype changes in analytics schemas.
            raise AssertionError(f"Unexpected dtype for {table}.{name}: {dtype_name}")
    return row


_ANALYTICS_POSITIVE_ID_CASES = [
    (table, field, invalid_value)
    for table in _ANALYTICS_TABLES
    for field in _positive_int_id_fields(table)
    for invalid_value in (0, -1)
]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_analytics_schemas_are_discovered() -> None:
    discovered = set(_star_schema_map().keys())
    missing = [t for t in _ANALYTICS_TABLES if t not in discovered]
    assert not missing, f"Missing from _star_schema_map: {missing}"


# ---------------------------------------------------------------------------
# Per-schema validation
# ---------------------------------------------------------------------------


class TestAnalyticsClutchPerformanceSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_clutch_performance",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "clutch_window": "Last 5 Minutes",
                "player_name": "LeBron James",
                "team_abbreviation": "LAL",
                "gp": 71,
                "w": 45,
                "l": 26,
                "min": 120.5,
                "fgm": 35.0,
                "fga": 72.0,
                "fg_pct": 0.486,
                "fg3m": 8.0,
                "fg3a": 22.0,
                "fg3_pct": 0.364,
                "ftm": 18.0,
                "fta": 24.0,
                "ft_pct": 0.750,
                "oreb": 5.0,
                "dreb": 18.0,
                "reb": 23.0,
                "ast": 22.0,
                "tov": 10.0,
                "stl": 6.0,
                "blk": 3.0,
                "pf": 8.0,
                "pts": 96.0,
                "plus_minus": 42.0,
                "net_rating": 12.5,
                "off_rating": 118.3,
                "def_rating": 105.8,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_clutch_performance",
            {
                "player_id": 201935,
                "team_id": 1610612745,
                "season_year": "2024-25",
                "clutch_window": "Last 5 Minutes",
                "player_name": None,
                "team_abbreviation": None,
                "gp": None,
                "w": None,
                "l": None,
                "min": None,
                "fgm": None,
                "fga": None,
                "fg_pct": None,
                "fg3m": None,
                "fg3a": None,
                "fg3_pct": None,
                "ftm": None,
                "fta": None,
                "ft_pct": None,
                "oreb": None,
                "dreb": None,
                "reb": None,
                "ast": None,
                "tov": None,
                "stl": None,
                "blk": None,
                "pf": None,
                "pts": None,
                "plus_minus": None,
                "net_rating": None,
                "off_rating": None,
                "def_rating": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsDraftValueSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_draft_value",
            {
                "person_id": 2544,
                "season": "2003",
                "round_number": 1,
                "round_pick": 1,
                "overall_pick": 1,
                "team_id": 1610612739,
                "player_name": "LeBron James",
                "position": "F",
                "country": "USA",
                "career_gp": 1487,
                "career_pts": 42000.0,
                "career_ppg": 27.2,
                "career_rpg": 7.5,
                "career_apg": 7.4,
                "career_fg_pct": 0.504,
                "career_fg3_pct": 0.345,
                "seasons_played": 22,
                "first_season": "2003-04",
                "last_season": "2024-25",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_draft_value",
            {
                "person_id": 9999,
                "season": "2020",
                "round_number": None,
                "round_pick": None,
                "overall_pick": None,
                "team_id": None,
                "player_name": None,
                "position": None,
                "country": None,
                "career_gp": None,
                "career_pts": None,
                "career_ppg": None,
                "career_rpg": None,
                "career_apg": None,
                "career_fg_pct": None,
                "career_fg3_pct": None,
                "seasons_played": None,
                "first_season": None,
                "last_season": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsGameSummarySchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_game_summary",
            {
                "game_id": "0022401000",
                "game_date": "2025-01-15",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "matchup": "LAL vs. BOS",
                "arena_name": "Crypto.com Arena",
                "home_team_id": 1610612747,
                "home_team_name": "Los Angeles Lakers",
                "home_team_abbreviation": "LAL",
                "away_team_id": 1610612738,
                "away_team_name": "Boston Celtics",
                "away_team_abbreviation": "BOS",
                "pts_home": 112.0,
                "pts_away": 105.0,
                "plus_minus_home": 7.0,
                "wl_home": "W",
                "pts_qtr1_home": 28.0,
                "pts_qtr2_home": 30.0,
                "pts_qtr3_home": 26.0,
                "pts_qtr4_home": 28.0,
                "pts_ot1_home": 0.0,
                "pts_ot2_home": 0.0,
                "pts_qtr1_away": 24.0,
                "pts_qtr2_away": 27.0,
                "pts_qtr3_away": 29.0,
                "pts_qtr4_away": 25.0,
                "pts_ot1_away": 0.0,
                "pts_ot2_away": 0.0,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_game_summary",
            {
                "game_id": "0022400001",
                "game_date": "2024-10-22",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "matchup": None,
                "arena_name": None,
                "home_team_id": None,
                "home_team_name": None,
                "home_team_abbreviation": None,
                "away_team_id": None,
                "away_team_name": None,
                "away_team_abbreviation": None,
                "pts_home": None,
                "pts_away": None,
                "plus_minus_home": None,
                "wl_home": None,
                "pts_qtr1_home": None,
                "pts_qtr2_home": None,
                "pts_qtr3_home": None,
                "pts_qtr4_home": None,
                "pts_ot1_home": None,
                "pts_ot2_home": None,
                "pts_qtr1_away": None,
                "pts_qtr2_away": None,
                "pts_qtr3_away": None,
                "pts_qtr4_away": None,
                "pts_ot1_away": None,
                "pts_ot2_away": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsHeadToHeadSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_head_to_head",
            {
                "team_id": 1610612747,
                "opponent_team_id": 1610612738,
                "season_year": "2024-25",
                "team_abbr": "LAL",
                "opponent_abbr": "BOS",
                "games_played": 4,
                "wins": 3,
                "losses": 1,
                "avg_pts_scored": 112.5,
                "avg_pts_allowed": 106.0,
                "avg_margin": 6.5,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_head_to_head",
            {
                "team_id": 1610612762,
                "opponent_team_id": 1610612744,
                "season_year": "2024-25",
                "team_abbr": None,
                "opponent_abbr": None,
                "games_played": 2,
                "wins": 1,
                "losses": 1,
                "avg_pts_scored": None,
                "avg_pts_allowed": None,
                "avg_margin": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsLeagueBenchmarksSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_league_benchmarks",
            {
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "total_players": 540,
                "league_avg_ppg": 15.2,
                "league_avg_rpg": 4.8,
                "league_avg_apg": 3.2,
                "league_avg_spg": 0.9,
                "league_avg_bpg": 0.5,
                "league_avg_fg_pct": 0.468,
                "league_avg_fg3_pct": 0.365,
                "league_avg_ft_pct": 0.780,
                "league_avg_ts_pct": 0.580,
                "league_avg_usg_pct": 0.200,
                "total_teams": 30,
                "league_avg_team_ppg": 112.5,
                "league_avg_team_rpg": 43.2,
                "league_avg_team_apg": 25.8,
                "league_avg_team_fg_pct": 0.472,
                "league_avg_team_fg3_pct": 0.368,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_league_benchmarks",
            {
                "season_year": "2024-25",
                "season_type": "Playoffs",
                "total_players": 200,
                "league_avg_ppg": None,
                "league_avg_rpg": None,
                "league_avg_apg": None,
                "league_avg_spg": None,
                "league_avg_bpg": None,
                "league_avg_fg_pct": None,
                "league_avg_fg3_pct": None,
                "league_avg_ft_pct": None,
                "league_avg_ts_pct": None,
                "league_avg_usg_pct": None,
                "total_teams": None,
                "league_avg_team_ppg": None,
                "league_avg_team_rpg": None,
                "league_avg_team_apg": None,
                "league_avg_team_fg_pct": None,
                "league_avg_team_fg3_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsPlayerGameCompleteSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_player_game_complete",
            {
                "player_id": 2544,
                "game_id": "0022401000",
                "team_id": 1610612747,
                "season_year": "2024-25",
                "game_date": "2025-01-15",
                "player_name": "LeBron James",
                "team_abbreviation": "LAL",
                # traditional
                "min": 36.5,
                "pts": 28.0,
                "reb": 8.0,
                "ast": 10.0,
                "stl": 2.0,
                "blk": 1.0,
                "tov": 3.0,
                "fgm": 11.0,
                "fga": 20.0,
                "fg_pct": 0.550,
                "fg3m": 3.0,
                "fg3a": 7.0,
                "fg3_pct": 0.429,
                "ftm": 3.0,
                "fta": 4.0,
                "ft_pct": 0.750,
                "oreb": 1.0,
                "dreb": 7.0,
                "pf": 2.0,
                "plus_minus": 12.0,
                # advanced
                "off_rating": 125.4,
                "def_rating": 108.2,
                "net_rating": 17.2,
                "ast_pct": 0.48,
                "ast_ratio": 0.35,
                "reb_pct": 0.12,
                "oreb_pct": 0.03,
                "dreb_pct": 0.21,
                "efg_pct": 0.625,
                "ts_pct": 0.650,
                "pace": 100.2,
                "pie": 0.22,
                # misc
                "pts_off_tov": 5.0,
                "second_chance_pts": 3.0,
                "fbps": 8.0,
                "pitp": 12.0,
                "usg_pct": 0.30,
                # hustle
                "contested_shots": 4.0,
                "deflections": 3.0,
                "loose_balls_recovered": 1.0,
                "charges_drawn": 0.0,
                "screen_assists": 2.0,
                # tracking
                "dist": 2.8,
                "spd": 4.5,
                "tchs": 85.0,
                "passes": 52.0,
                "dfg_pct": 0.42,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_player_game_complete",
            {
                "player_id": 201935,
                "game_id": "0022400001",
                "team_id": 1610612745,
                "season_year": None,
                "game_date": None,
                "player_name": None,
                "team_abbreviation": None,
                "min": None,
                "pts": None,
                "reb": None,
                "ast": None,
                "stl": None,
                "blk": None,
                "tov": None,
                "fgm": None,
                "fga": None,
                "fg_pct": None,
                "fg3m": None,
                "fg3a": None,
                "fg3_pct": None,
                "ftm": None,
                "fta": None,
                "ft_pct": None,
                "oreb": None,
                "dreb": None,
                "pf": None,
                "plus_minus": None,
                "off_rating": None,
                "def_rating": None,
                "net_rating": None,
                "ast_pct": None,
                "ast_ratio": None,
                "reb_pct": None,
                "oreb_pct": None,
                "dreb_pct": None,
                "efg_pct": None,
                "ts_pct": None,
                "pace": None,
                "pie": None,
                "pts_off_tov": None,
                "second_chance_pts": None,
                "fbps": None,
                "pitp": None,
                "usg_pct": None,
                "contested_shots": None,
                "deflections": None,
                "loose_balls_recovered": None,
                "charges_drawn": None,
                "screen_assists": None,
                "dist": None,
                "spd": None,
                "tchs": None,
                "passes": None,
                "dfg_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsPlayerImpactSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_player_impact",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "player_name": "LeBron James",
                "team_abbreviation": "LAL",
                "gp": 71,
                "avg_min": 33.8,
                "avg_pts": 25.7,
                "avg_reb": 7.3,
                "avg_ast": 8.3,
                "fg_pct": 0.540,
                "fg3_pct": 0.410,
                "ft_pct": 0.745,
                "avg_off_rating": 121.3,
                "avg_def_rating": 110.5,
                "avg_net_rating": 10.8,
                "avg_ts_pct": 0.621,
                "avg_usg_pct": 0.290,
                "avg_pie": 0.168,
                "on_off_rating": 118.5,
                "on_def_rating": 107.2,
                "on_net_rating": 11.3,
                "on_pts": 112.0,
                "on_reb": 44.5,
                "on_ast": 27.0,
                "off_off_rating": 110.2,
                "off_def_rating": 112.8,
                "off_net_rating": -2.6,
                "net_rating_diff": 13.9,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_player_impact",
            {
                "player_id": 201935,
                "team_id": 1610612745,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "player_name": None,
                "team_abbreviation": None,
                "gp": None,
                "avg_min": None,
                "avg_pts": None,
                "avg_reb": None,
                "avg_ast": None,
                "fg_pct": None,
                "fg3_pct": None,
                "ft_pct": None,
                "avg_off_rating": None,
                "avg_def_rating": None,
                "avg_net_rating": None,
                "avg_ts_pct": None,
                "avg_usg_pct": None,
                "avg_pie": None,
                "on_off_rating": None,
                "on_def_rating": None,
                "on_net_rating": None,
                "on_pts": None,
                "on_reb": None,
                "on_ast": None,
                "off_off_rating": None,
                "off_def_rating": None,
                "off_net_rating": None,
                "net_rating_diff": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsPlayerMatchupSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_player_matchup",
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "vs_player_id": 201142,
                "season_year": "2024-25",
                "player_name": "LeBron James",
                "team_abbreviation": "LAL",
                "vs_player_name": "Kevin Durant",
                "matchup_min": 48.5,
                "player_pts": 52.0,
                "team_pts": 220.0,
                "ast": 18.0,
                "tov": 6.0,
                "stl": 4.0,
                "blk": 2.0,
                "fgm": 20.0,
                "fga": 42.0,
                "fg_pct": 0.476,
                "fg3m": 5.0,
                "fg3a": 14.0,
                "fg3_pct": 0.357,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_player_matchup",
            {
                "player_id": 201935,
                "team_id": 1610612745,
                "vs_player_id": 203507,
                "season_year": "2024-25",
                "player_name": None,
                "team_abbreviation": None,
                "vs_player_name": None,
                "matchup_min": None,
                "player_pts": None,
                "team_pts": None,
                "ast": None,
                "tov": None,
                "stl": None,
                "blk": None,
                "fgm": None,
                "fga": None,
                "fg_pct": None,
                "fg3m": None,
                "fg3a": None,
                "fg3_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsPlayerSeasonCompleteSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_player_season_complete",
            {
                "player_id": 2544,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "team_id": 1610612747,
                "player_name": "LeBron James",
                "team_abbreviation": "LAL",
                "gp": 71,
                "total_min": 2400.0,
                "total_pts": 1825.0,
                "total_reb": 518.0,
                "total_ast": 590.0,
                "total_stl": 92.0,
                "total_blk": 43.0,
                "total_tov": 254.0,
                "avg_pts": 25.7,
                "avg_reb": 7.3,
                "avg_ast": 8.3,
                "fg_pct": 0.540,
                "fg3_pct": 0.410,
                "ft_pct": 0.745,
                "avg_off_rating": 121.3,
                "avg_def_rating": 110.5,
                "avg_net_rating": 10.8,
                "avg_pie": 0.168,
                # per-36
                "pts_per36": 27.4,
                "reb_per36": 7.8,
                "ast_per36": 8.8,
                "stl_per36": 1.4,
                "blk_per36": 0.6,
                "tov_per36": 3.8,
                # per-48
                "pts_per48": 36.5,
                "reb_per48": 10.4,
                "ast_per48": 11.8,
                "stl_per48": 1.8,
                "blk_per48": 0.9,
                "tov_per48": 5.1,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_player_season_complete",
            {
                "player_id": 201935,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "team_id": 1610612745,
                "player_name": None,
                "team_abbreviation": None,
                "gp": None,
                "total_min": None,
                "total_pts": None,
                "total_reb": None,
                "total_ast": None,
                "total_stl": None,
                "total_blk": None,
                "total_tov": None,
                "avg_pts": None,
                "avg_reb": None,
                "avg_ast": None,
                "fg_pct": None,
                "fg3_pct": None,
                "ft_pct": None,
                "avg_off_rating": None,
                "avg_def_rating": None,
                "avg_net_rating": None,
                "avg_pie": None,
                "pts_per36": None,
                "reb_per36": None,
                "ast_per36": None,
                "stl_per36": None,
                "blk_per36": None,
                "tov_per36": None,
                "pts_per48": None,
                "reb_per48": None,
                "ast_per48": None,
                "stl_per48": None,
                "blk_per48": None,
                "tov_per48": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsShootingEfficiencySchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_shooting_efficiency",
            {
                "player_id": 2544,
                "game_id": "0022401000",
                "team_id": 1610612747,
                "player_name": "LeBron James",
                "season_year": "2024-25",
                "game_date": "2025-01-15",
                "shot_zone_basic": "Mid-Range",
                "shot_zone_area": "Center(C)",
                "shot_zone_range": "16-24 ft.",
                "shot_distance": 18.3,
                "shot_type": "2PT Field Goal",
                "shot_made_flag": 1,
                "loc_x": 5.2,
                "loc_y": 14.8,
                "league_avg_fgm": 3200.0,
                "league_avg_fga": 7500.0,
                "league_avg_fg_pct": 0.427,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_shooting_efficiency",
            {
                "player_id": 201935,
                "game_id": "0022400001",
                "team_id": 1610612745,
                "player_name": None,
                "season_year": None,
                "game_date": None,
                "shot_zone_basic": None,
                "shot_zone_area": None,
                "shot_zone_range": None,
                "shot_distance": None,
                "shot_type": None,
                "shot_made_flag": None,
                "loc_x": None,
                "loc_y": None,
                "league_avg_fgm": None,
                "league_avg_fga": None,
                "league_avg_fg_pct": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsTeamGameCompleteSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_team_game_complete",
            {
                "team_id": 1610612747,
                "game_id": "0022401000",
                "season_year": "2024-25",
                "game_date": "2025-01-15",
                "team_name": "Los Angeles Lakers",
                "team_abbreviation": "LAL",
                # traditional
                "pts": 112.0,
                "reb": 44.0,
                "ast": 27.0,
                "stl": 8.0,
                "blk": 5.0,
                "tov": 13.0,
                "fgm": 42.0,
                "fga": 88.0,
                "fg_pct": 0.477,
                "fg3m": 12.0,
                "fg3a": 32.0,
                "fg3_pct": 0.375,
                "ftm": 16.0,
                "fta": 20.0,
                "ft_pct": 0.800,
                "oreb": 10.0,
                "dreb": 34.0,
                "pf": 18.0,
                "plus_minus": 7.0,
                # advanced
                "off_rating": 118.5,
                "def_rating": 110.2,
                "net_rating": 8.3,
                "ast_pct": 0.64,
                "reb_pct": 0.52,
                "oreb_pct": 0.28,
                "dreb_pct": 0.76,
                "efg_pct": 0.545,
                "ts_pct": 0.575,
                "pace": 99.8,
                "pie": 0.55,
                # misc
                "pts_off_tov": 18.0,
                "second_chance_pts": 12.0,
                "fbps": 14.0,
                "pitp": 48.0,
                # hustle
                "contested_shots": 45.0,
                "deflections": 13.0,
                "loose_balls_recovered": 7.0,
                "charges_drawn": 2.0,
                "screen_assists": 10.0,
                # tracking
                "dist": 58.2,
                "spd": 4.6,
                "tchs": 320.0,
                "passes": 280.0,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_team_game_complete",
            {
                "team_id": 1610612738,
                "game_id": "0022400001",
                "season_year": None,
                "game_date": None,
                "team_name": None,
                "team_abbreviation": None,
                "pts": None,
                "reb": None,
                "ast": None,
                "stl": None,
                "blk": None,
                "tov": None,
                "fgm": None,
                "fga": None,
                "fg_pct": None,
                "fg3m": None,
                "fg3a": None,
                "fg3_pct": None,
                "ftm": None,
                "fta": None,
                "ft_pct": None,
                "oreb": None,
                "dreb": None,
                "pf": None,
                "plus_minus": None,
                "off_rating": None,
                "def_rating": None,
                "net_rating": None,
                "ast_pct": None,
                "reb_pct": None,
                "oreb_pct": None,
                "dreb_pct": None,
                "efg_pct": None,
                "ts_pct": None,
                "pace": None,
                "pie": None,
                "pts_off_tov": None,
                "second_chance_pts": None,
                "fbps": None,
                "pitp": None,
                "contested_shots": None,
                "deflections": None,
                "loose_balls_recovered": None,
                "charges_drawn": None,
                "screen_assists": None,
                "dist": None,
                "spd": None,
                "tchs": None,
                "passes": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestAnalyticsTeamSeasonSummarySchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "analytics_team_season_summary",
            {
                "team_id": 1610612738,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "team_name": "Boston Celtics",
                "team_abbreviation": "BOS",
                "gp": 82,
                "avg_pts": 118.7,
                "avg_reb": 44.4,
                "avg_ast": 27.1,
                "fg_pct": 0.485,
                "fg3_pct": 0.374,
                "ft_pct": 0.778,
                "wins": 64,
                "losses": 18,
                "win_pct": 0.780,
                "conference": "East",
                "conference_rank": 1,
                "division": "Atlantic",
                "division_rank": 1,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "analytics_team_season_summary",
            {
                "team_id": 1610612762,
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "team_name": None,
                "team_abbreviation": None,
                "gp": None,
                "avg_pts": None,
                "avg_reb": None,
                "avg_ast": None,
                "fg_pct": None,
                "fg3_pct": None,
                "ft_pct": None,
                "wins": None,
                "losses": None,
                "win_pct": None,
                "conference": None,
                "conference_rank": None,
                "division": None,
                "division_rank": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


# ---------------------------------------------------------------------------
# ID guardrails
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [table for table in _ANALYTICS_TABLES if _positive_int_id_fields(table)],
)
def test_positive_integer_id_fields_have_gt_zero_checks(table: str) -> None:
    schema = _star_schema_map()[table].to_schema()

    for field in _positive_int_id_fields(table):
        checks = schema.columns[field].checks
        assert any(
            check.name == "greater_than" and check.statistics.get("min_value") == 0
            for check in checks
        ), f"{table}.{field} should require values greater than zero"


@pytest.mark.parametrize(
    ("table", "field", "invalid_value"),
    _ANALYTICS_POSITIVE_ID_CASES,
)
def test_analytics_schemas_reject_non_positive_integer_ids(
    table: str, field: str, invalid_value: int
) -> None:
    import pandera.errors

    row = _synthetic_valid_row(table)
    assert isinstance(_validate(table, row), pl.DataFrame)

    row[field] = invalid_value
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        _validate(table, row)
