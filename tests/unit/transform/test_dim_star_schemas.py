"""Focused tests for selected dim_* Pandera star-schema contracts."""

from __future__ import annotations

import polars as pl
import pytest

from nbadb.transform.pipeline import _star_schema_map

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FOCUSED_DIM_TABLES = [
    "dim_all_players",
    "dim_defunct_team",
    "dim_schedule_int",
    "dim_season_week",
    "dim_team_extended",
]


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({k: [v] for k, v in values.items()})


def _validate(table: str, row: dict[str, object]) -> pl.DataFrame:
    schema_cls = _star_schema_map()[table]
    return schema_cls.validate(_frame(row))


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
    ],
)
def test_schema_rejects_invalid_data(
    table: str, bad_row: dict[str, object], description: str
) -> None:
    import pandera.errors

    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        _validate(table, bad_row)
