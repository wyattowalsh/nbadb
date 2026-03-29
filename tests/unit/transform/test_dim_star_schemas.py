"""Focused tests for representative dim_* Pandera star-schema contracts."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.dimensions.dim_date import DimDateTransformer
from nbadb.transform.dimensions.dim_game import DimGameTransformer
from nbadb.transform.dimensions.dim_player import DimPlayerTransformer
from nbadb.transform.dimensions.dim_team import DimTeamTransformer
from nbadb.transform.pipeline import _star_schema_map

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FOCUSED_DIM_TABLES = [
    "dim_all_players",
    "dim_date",
    "dim_defunct_team",
    "dim_game",
    "dim_player",
    "dim_schedule_int",
    "dim_season_week",
    "dim_team",
    "dim_team_extended",
    "dim_team_history",
]


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({k: [v] for k, v in values.items()})


def _validate_frame(table: str, df: pl.DataFrame) -> pl.DataFrame:
    schema_cls = _star_schema_map()[table]
    return schema_cls.validate(df)


def _validate(table: str, row: dict[str, object]) -> pl.DataFrame:
    return _validate_frame(table, _frame(row))


def _run_sql_transform(
    transformer, staging: dict[str, pl.LazyFrame]
) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_focused_dim_schemas_are_discovered() -> None:
    discovered = set(_star_schema_map().keys())
    missing = [t for t in _FOCUSED_DIM_TABLES if t not in discovered]
    assert not missing, f"Missing from _star_schema_map: {missing}"


# ---------------------------------------------------------------------------
# Per-schema validation
# ---------------------------------------------------------------------------


class TestDimAllPlayersSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_all_players",
            {
                "person_id": 2544,
                "display_last_comma_first": "James, LeBron",
                "display_first_last": "LeBron James",
                "roster_status": 1,
                "from_year": "2003",
                "to_year": "2025",
                "playercode": "lebron_james",
                "team_id": 1610612747,
                "team_city": "Los Angeles",
                "team_name": "Lakers",
                "team_abbreviation": "LAL",
                "team_code": "lakers",
                "games_played_flag": "Y",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_all_players",
            {
                "person_id": 201935,
                "display_last_comma_first": None,
                "display_first_last": "James Harden",
                "roster_status": None,
                "from_year": None,
                "to_year": None,
                "playercode": None,
                "team_id": None,
                "team_city": None,
                "team_name": None,
                "team_abbreviation": None,
                "team_code": None,
                "games_played_flag": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestDimDefunctTeamSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_defunct_team",
            {
                "league_id": "00",
                "team_id": 1610610000,
                "team_city": "Baltimore",
                "team_name": "Bullets",
                "start_year": "1963",
                "end_year": "1972",
                "years": 10,
                "games": 820,
                "wins": 410,
                "losses": 410,
                "win_pct": 0.500,
                "po_appearances": 5,
                "div_titles": 2,
                "conf_titles": 0,
                "league_titles": 1,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_defunct_team",
            {
                "league_id": "00",
                "team_id": 1610610001,
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
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestDimDateSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_date",
            {
                "date_key": 20250115,
                "full_date": "2025-01-15",
                "year": 2025,
                "month": 1,
                "day": 15,
                "day_of_week": 3,
                "day_name": "Wednesday",
                "month_name": "January",
                "is_weekend": False,
                "nba_season": "2024-25",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_date",
            {
                "date_key": 20250704,
                "full_date": "2025-07-04",
                "year": 2025,
                "month": 7,
                "day": 4,
                "day_of_week": 5,
                "day_name": "Friday",
                "month_name": "July",
                "is_weekend": False,
                "nba_season": None,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_transform_output_validates_schema(self) -> None:
        result = DimDateTransformer().transform({})
        sample = result.filter(
            (pl.col("date_key") == 20240101) | (pl.col("date_key") == 20241001)
        ).sort("date_key")

        validated = _validate_frame("dim_date", sample)

        assert sample.shape == (2, 11)
        assert sample["nba_season"].to_list() == ["2023-24", "2024-25"]
        assert "date" not in validated.columns


class TestDimGameSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_game",
            {
                "game_id": "0022400456",
                "game_date": "2025-01-15",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "home_team_id": 1610612747,
                "visitor_team_id": 1610612738,
                "matchup": "LAL vs. BOS",
                "arena_name": "Crypto.com Arena",
                "arena_city": "Los Angeles",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_game",
            {
                "game_id": "0022400457",
                "game_date": "2025-01-17",
                "season_year": "2024-25",
                "season_type": None,
                "home_team_id": None,
                "visitor_team_id": None,
                "matchup": None,
                "arena_name": None,
                "arena_city": None,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_transform_output_validates_schema(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["0022400001", "0022400002"],
                "game_date": ["2024-10-22", "2024-10-23"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [1610612747, 1610612738],
                "visitor_team_id": [1610612750, 1610612752],
                "matchup": ["LAL vs. MIN", "BOS vs. NYK"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "arena_name": ["Crypto.com Arena"],
                "arena_city": ["Los Angeles"],
            }
        )

        result = DimGameTransformer().transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )

        validated = _validate_frame("dim_game", result)

        assert result.shape == (2, 9)
        assert result.filter(pl.col("game_id") == "0022400002")["arena_name"][0] is None
        assert validated.shape == result.shape


class TestDimPlayerSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_player",
            {
                "player_sk": 1,
                "player_id": 2544,
                "full_name": "LeBron James",
                "first_name": "LeBron",
                "last_name": "James",
                "is_active": True,
                "team_id": 1610612747,
                "position": "F",
                "jersey_number": "23",
                "height": "6-9",
                "weight": 250,
                "birth_date": "1984-12-30",
                "country": "USA",
                "college_id": 1,
                "draft_year": 2003,
                "draft_round": 1,
                "draft_number": 1,
                "from_year": 2003,
                "to_year": 2025,
                "valid_from": "2003-04",
                "valid_to": None,
                "is_current": True,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_player",
            {
                "player_sk": 2,
                "player_id": 201935,
                "full_name": "James Harden",
                "first_name": None,
                "last_name": None,
                "is_active": None,
                "team_id": None,
                "position": None,
                "jersey_number": None,
                "height": None,
                "weight": None,
                "birth_date": None,
                "country": None,
                "college_id": None,
                "draft_year": None,
                "draft_round": None,
                "draft_number": None,
                "from_year": None,
                "to_year": None,
                "valid_from": "2009-10",
                "valid_to": "2024-25",
                "is_current": False,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_transform_output_validates_schema(self) -> None:
        staging = {
            "stg_player_info": pl.DataFrame(
                {
                    "player_id": [1, 1, 2],
                    "full_name": ["Player A", "Player A", "Player B"],
                    "first_name": ["Player", "Player", "Player"],
                    "last_name": ["A", "A", "B"],
                    "roster_status": ["Active", "Active", "Inactive"],
                    "team_id": [10, 20, 30],
                    "position": ["G", "G", "F"],
                    "jersey_number": ["1", "1", "5"],
                    "height": ["6-3", "6-3", "6-8"],
                    "weight": [190, 190, 240],
                    "birth_date": ["1990-01-01", "1990-01-01", "1992-05-15"],
                    "country": ["USA", "USA", "Greece"],
                    "draft_year": [2012, 2012, 2013],
                    "draft_round": [1, 1, 1],
                    "draft_number": [4, 4, 15],
                    "college_id": [None, None, None],
                    "from_year": ["2012", "2012", "2013"],
                    "to_year": ["2025", "2025", "2020"],
                    "season": ["2023-24", "2024-25", "2024-25"],
                }
            ).lazy()
        }

        result = _run_sql_transform(DimPlayerTransformer(), staging)
        validated = _validate_frame("dim_player", result)
        player_one = result.filter(pl.col("player_id") == 1).sort("valid_from")

        assert result.shape[0] == 3
        assert player_one["is_current"].to_list() == [False, True]
        assert player_one["valid_to"][0] == "2024-25"
        assert validated.shape == result.shape


class TestDimScheduleIntSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_schedule_int",
            {
                "game_id": "0012400001",
                "game_code": "20250115/BOSLAL",
                "league_id": "00",
                "season_year": "2024-25",
                "game_date": "2025-01-15",
                "game_date_est": "2025-01-15",
                "game_date_time_est": "2025-01-15T19:30:00",
                "game_date_utc": "2025-01-16",
                "game_time_utc": "00:30:00",
                "game_date_time_utc": "2025-01-16T00:30:00",
                "game_status": 3,
                "game_status_text": "Final",
                "game_sequence": 1,
                "week_number": 12,
                "week_name": "Week 12",
                "day_of_week": "Wed",
                "arena_name": "Crypto.com Arena",
                "arena_city": "Los Angeles",
                "arena_state": "CA",
                "home_team_id": 1610612747,
                "home_team_name": "Lakers",
                "home_team_city": "Los Angeles",
                "home_team_tricode": "LAL",
                "home_team_wins": 20,
                "home_team_losses": 18,
                "home_team_score": 112,
                "away_team_id": 1610612738,
                "away_team_name": "Celtics",
                "away_team_city": "Boston",
                "away_team_tricode": "BOS",
                "away_team_wins": 30,
                "away_team_losses": 8,
                "away_team_score": 105,
                "if_necessary": "",
                "series_text": "",
                "game_subtype": "",
                "is_neutral": "",
                "postponed_status": "",
                "week_start_date": "2025-01-13",
                "week_end_date": "2025-01-19",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_schedule_int",
            {
                "game_id": "0012400002",
                "game_code": None,
                "league_id": None,
                "season_year": None,
                "game_date": None,
                "game_date_est": None,
                "game_date_time_est": None,
                "game_date_utc": None,
                "game_time_utc": None,
                "game_date_time_utc": None,
                "game_status": None,
                "game_status_text": None,
                "game_sequence": None,
                "week_number": None,
                "week_name": None,
                "day_of_week": None,
                "arena_name": None,
                "arena_city": None,
                "arena_state": None,
                "home_team_id": None,
                "home_team_name": None,
                "home_team_city": None,
                "home_team_tricode": None,
                "home_team_wins": None,
                "home_team_losses": None,
                "home_team_score": None,
                "away_team_id": None,
                "away_team_name": None,
                "away_team_city": None,
                "away_team_tricode": None,
                "away_team_wins": None,
                "away_team_losses": None,
                "away_team_score": None,
                "if_necessary": None,
                "series_text": None,
                "game_subtype": None,
                "is_neutral": None,
                "postponed_status": None,
                "week_start_date": None,
                "week_end_date": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestDimSeasonWeekSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_season_week",
            {
                "season_id": "22024",
                "week_number": 12,
                "start_date": "2025-01-06",
                "end_date": "2025-01-12",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_season_week",
            {
                "season_id": None,
                "week_number": None,
                "start_date": None,
                "end_date": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestDimTeamSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_team",
            {
                "team_id": 1610612738,
                "abbreviation": "BOS",
                "full_name": "Boston Celtics",
                "city": "Boston",
                "state": "MA",
                "arena": "TD Garden",
                "year_founded": 1946,
                "conference": "East",
                "division": "Atlantic",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_team",
            {
                "team_id": 1610612762,
                "abbreviation": "UTA",
                "full_name": "Utah Jazz",
                "city": None,
                "state": None,
                "arena": None,
                "year_founded": None,
                "conference": None,
                "division": None,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_transform_output_validates_schema(self) -> None:
        staging = {
            "stg_team_info": pl.DataFrame(
                {
                    "team_id": [1, 1, 2],
                    "abbreviation": ["BOS", "BOS", "LAL"],
                    "full_name": [
                        "Boston Celtics",
                        "Boston Celtics",
                        "Los Angeles Lakers",
                    ],
                    "city": ["Boston", "Boston", None],
                    "state": ["MA", "MA", None],
                    "arena": ["Old Garden", "TD Garden", None],
                    "year_founded": [1946, 1946, None],
                    "conference": ["East", "East", None],
                    "division": ["Atlantic", "Atlantic", None],
                }
            ).lazy()
        }

        result = DimTeamTransformer().transform(staging)
        validated = _validate_frame("dim_team", result)

        assert result.shape == (2, 9)
        assert result["team_id"].to_list() == [1, 2]
        assert result.filter(pl.col("team_id") == 1)["arena"][0] == "TD Garden"
        assert validated.shape == result.shape


class TestDimTeamExtendedSchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_team_extended",
            {
                "team_id": 1610612738,
                "abbreviation": "BOS",
                "nickname": "Celtics",
                "yearfounded": 1946,
                "city": "Boston",
                "arena": "TD Garden",
                "arenacapacity": 19156,
                "owner": "Wyc Grousbeck",
                "generalmanager": "Brad Stevens",
                "headcoach": "Joe Mazzulla",
                "dleagueaffiliation": "Maine Celtics",
                "season_year": "2024-25",
                "team_city": "Boston",
                "team_name": "Celtics",
                "team_abbreviation": "BOS",
                "team_conference": "East",
                "team_division": "Atlantic",
                "team_code": "celtics",
                "team_slug": "celtics",
                "w": 64,
                "l": 18,
                "pct": 0.780,
                "conf_rank": 1,
                "div_rank": 1,
                "min_year": "1946",
                "max_year": "2025",
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_team_extended",
            {
                "team_id": 1610612762,
                "abbreviation": "UTA",
                "nickname": "Jazz",
                "yearfounded": None,
                "city": None,
                "arena": None,
                "arenacapacity": None,
                "owner": None,
                "generalmanager": None,
                "headcoach": None,
                "dleagueaffiliation": None,
                "season_year": None,
                "team_city": None,
                "team_name": "Jazz",
                "team_abbreviation": "UTA",
                "team_conference": None,
                "team_division": None,
                "team_code": None,
                "team_slug": None,
                "w": None,
                "l": None,
                "pct": None,
                "conf_rank": None,
                "div_rank": None,
                "min_year": None,
                "max_year": None,
            },
        )
        assert isinstance(result, pl.DataFrame)


class TestDimTeamHistorySchema:
    def test_valid_row(self) -> None:
        result = _validate(
            "dim_team_history",
            {
                "team_history_sk": 1,
                "team_id": 1610612751,
                "city": "Brooklyn",
                "nickname": "Nets",
                "abbreviation": "BKN",
                "franchise_name": "Brooklyn Nets",
                "league_id": "00",
                "valid_from": "2012-13",
                "valid_to": None,
                "is_current": True,
            },
        )
        assert isinstance(result, pl.DataFrame)

    def test_nullable_fields(self) -> None:
        result = _validate(
            "dim_team_history",
            {
                "team_history_sk": 2,
                "team_id": 1610612751,
                "city": None,
                "nickname": None,
                "abbreviation": None,
                "franchise_name": None,
                "league_id": None,
                "valid_from": "1976-77",
                "valid_to": "2011-12",
                "is_current": False,
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
            "dim_all_players",
            {
                "person_id": -1,
                "display_last_comma_first": "Bad, Player",
                "display_first_last": "Bad Player",
                "roster_status": 1,
                "from_year": "2020",
                "to_year": "2025",
                "playercode": "bad_player",
                "team_id": 1610612747,
                "team_city": "Los Angeles",
                "team_name": "Lakers",
                "team_abbreviation": "LAL",
                "team_code": "lakers",
                "games_played_flag": "Y",
            },
            "person_id must be > 0",
        ),
        (
            "dim_date",
            {
                "date_key": 20251315,
                "full_date": "2025-13-15",
                "year": 2025,
                "month": 13,
                "day": 15,
                "day_of_week": 3,
                "day_name": "Wednesday",
                "month_name": "Smarch",
                "is_weekend": False,
                "nba_season": "2025-26",
            },
            "month must be between 1 and 12",
        ),
        (
            "dim_defunct_team",
            {
                "league_id": "00",
                "team_id": 0,
                "team_city": "Gone",
                "team_name": "Gone",
                "start_year": "1950",
                "end_year": "1960",
                "years": 10,
                "games": 100,
                "wins": 50,
                "losses": 50,
                "win_pct": 0.500,
                "po_appearances": 1,
                "div_titles": 0,
                "conf_titles": 0,
                "league_titles": 0,
            },
            "team_id must be > 0",
        ),
        (
            "dim_game",
            {
                "game_id": "0022400458",
                "game_date": "2025-01-19",
                "season_year": "2024-25",
                "season_type": "Regular Season",
                "home_team_id": 0,
                "visitor_team_id": 1610612744,
                "matchup": "LAL vs. GSW",
                "arena_name": "Crypto.com Arena",
                "arena_city": "Los Angeles",
            },
            "home_team_id must be > 0 when present",
        ),
        (
            "dim_player",
            {
                "player_sk": 0,
                "player_id": 2544,
                "full_name": "LeBron James",
                "first_name": "LeBron",
                "last_name": "James",
                "is_active": True,
                "team_id": 1610612747,
                "position": "F",
                "jersey_number": "23",
                "height": "6-9",
                "weight": 250,
                "birth_date": "1984-12-30",
                "country": "USA",
                "college_id": 1,
                "draft_year": 2003,
                "draft_round": 1,
                "draft_number": 1,
                "from_year": 2003,
                "to_year": 2025,
                "valid_from": "2003-04",
                "valid_to": None,
                "is_current": True,
            },
            "player_sk must be > 0",
        ),
        (
            "dim_team",
            {
                "team_id": 1610612738,
                "abbreviation": "BOS",
                "full_name": "Boston Celtics",
                "city": "Boston",
                "state": "MA",
                "arena": "TD Garden",
                "year_founded": 1900,
                "conference": "East",
                "division": "Atlantic",
            },
            "year_founded must be > 1900 when present",
        ),
        (
            "dim_team_extended",
            {
                "team_id": -5,
                "abbreviation": "BAD",
                "nickname": "Bad",
                "yearfounded": None,
                "city": None,
                "arena": None,
                "arenacapacity": None,
                "owner": None,
                "generalmanager": None,
                "headcoach": None,
                "dleagueaffiliation": None,
                "season_year": None,
                "team_city": None,
                "team_name": "Bad",
                "team_abbreviation": "BAD",
                "team_conference": None,
                "team_division": None,
                "team_code": None,
                "team_slug": None,
                "w": None,
                "l": None,
                "pct": None,
                "conf_rank": None,
                "div_rank": None,
                "min_year": None,
                "max_year": None,
            },
            "team_id must be > 0",
        ),
        (
            "dim_team_history",
            {
                "team_history_sk": 0,
                "team_id": 1610612751,
                "city": "Brooklyn",
                "nickname": "Nets",
                "abbreviation": "BKN",
                "franchise_name": "Brooklyn Nets",
                "league_id": "00",
                "valid_from": "2012-13",
                "valid_to": None,
                "is_current": True,
            },
            "team_history_sk must be > 0",
        ),
    ],
)
def test_schema_rejects_invalid_data(
    table: str, bad_row: dict[str, object], description: str
) -> None:
    import pandera.errors

    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        _validate(table, bad_row)
