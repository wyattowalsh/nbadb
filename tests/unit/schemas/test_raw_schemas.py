from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.raw.draft import RawDraftHistorySchema
from nbadb.schemas.raw.game_log import (
    RawLeagueGameLogSchema,
    RawPlayerGameLogSchema,
    RawTeamGameLogSchema,
)
from nbadb.schemas.raw.player import RawCommonAllPlayersSchema, RawPlayerIndexSchema

# -- RawCommonAllPlayersSchema ------------------------------------------------


def _common_all_players_row(**overrides: object) -> dict:
    base = {
        "person_id": 2544,
        "display_last_comma_first": "James, LeBron",
        "display_first_last": "LeBron James",
        "roster_status": 1,
        "from_year": "2003",
        "to_year": "2024",
        "playercode": "lebron_james",
        "team_id": 1610612747,
        "team_city": "Los Angeles",
        "team_name": "Lakers",
        "team_abbreviation": "LAL",
        "team_code": "lakers",
        "games_played_flag": "Y",
    }
    base.update(overrides)
    return base


class TestRawCommonAllPlayersSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_common_all_players_row())
        result = RawCommonAllPlayersSchema.validate(df)
        assert result.shape[0] == 1

    def test_person_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_common_all_players_row(person_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            RawCommonAllPlayersSchema.validate(df)

    def test_roster_status_isin_0_1(self) -> None:
        df = pl.DataFrame(_common_all_players_row(roster_status=5))
        with pytest.raises(pa_errors.SchemaError):
            RawCommonAllPlayersSchema.validate(df)

    def test_nullable_fields_accept_none(self) -> None:
        row = _common_all_players_row(
            display_last_comma_first=None,
            team_id=None,
            team_name=None,
        )
        df = pl.DataFrame(row)
        result = RawCommonAllPlayersSchema.validate(df)
        assert result.shape[0] == 1


# -- RawPlayerIndexSchema -----------------------------------------------------


def _player_index_row(**overrides: object) -> dict:
    base = {
        "person_id": 2544,
        "player_last_name": "James",
        "player_first_name": "LeBron",
        "player_slug": "lebron-james",
        "team_id": 1610612747,
        "team_slug": "lakers",
        "is_defunct": 0,
        "team_city": "Los Angeles",
        "team_name": "Lakers",
        "team_abbreviation": "LAL",
        "jersey_number": "23",
        "position": "Forward",
        "height": "6-9",
        "weight": "250",
        "college": None,
        "country": "USA",
        "draft_year": 2003,
        "draft_round": 1,
        "draft_number": 1,
        "roster_status": 1.0,
        "pts": 25.0,
        "reb": 7.0,
        "ast": 8.0,
        "stats_timeframe": "2024-25",
        "from_year": "2003",
        "to_year": "2024",
    }
    base.update(overrides)
    return base


class TestRawPlayerIndexSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_player_index_row())
        result = RawPlayerIndexSchema.validate(df)
        assert result.shape[0] == 1

    def test_person_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_player_index_row(person_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            RawPlayerIndexSchema.validate(df)

    def test_nullable_stats_accepted(self) -> None:
        df = pl.DataFrame(_player_index_row(pts=None, reb=None, ast=None))
        result = RawPlayerIndexSchema.validate(df)
        assert result.shape[0] == 1


# -- RawLeagueGameLogSchema ---------------------------------------------------


def _league_game_log_row(**overrides: object) -> dict:
    base = {
        "season_id": "22024",
        "team_id": 1610612747,
        "team_abbreviation": "LAL",
        "team_name": "Lakers",
        "game_id": "0022400001",
        "game_date": "2024-10-22",
        "matchup": "LAL vs. BOS",
        "wl": "W",
        "w": 1,
        "l": 0,
        "w_pct": 1.0,
        "min": 240.0,
        "fgm": 40.0,
        "fga": 85.0,
        "fg_pct": 0.471,
        "fg3m": 12.0,
        "fg3a": 35.0,
        "fg3_pct": 0.343,
        "ftm": 20.0,
        "fta": 25.0,
        "ft_pct": 0.800,
        "oreb": 10.0,
        "dreb": 35.0,
        "reb": 45.0,
        "ast": 25.0,
        "stl": 8.0,
        "blk": 5.0,
        "tov": 12.0,
        "pf": 18.0,
        "pts": 112.0,
        "plus_minus": 8.0,
        "video_available": 1,
    }
    base.update(overrides)
    return base


class TestRawLeagueGameLogSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_league_game_log_row())
        result = RawLeagueGameLogSchema.validate(df)
        assert result.shape[0] == 1

    def test_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_league_game_log_row(team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            RawLeagueGameLogSchema.validate(df)

    def test_season_id_required(self) -> None:
        row = _league_game_log_row()
        row["season_id"] = None
        df = pl.DataFrame(row)
        with pytest.raises(pa_errors.SchemaError):
            RawLeagueGameLogSchema.validate(df)

    def test_nullable_stat_fields(self) -> None:
        df = pl.DataFrame(_league_game_log_row(pts=None, reb=None, ast=None))
        result = RawLeagueGameLogSchema.validate(df)
        assert result.shape[0] == 1


class TestRawPlayerGameLogSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame({
            "season_id": ["22024"],
            "player_id": [2544],
            "game_id": ["0022400001"],
            "game_date": ["2024-10-22"],
            "matchup": ["LAL vs. BOS"],
            "wl": ["W"],
            "min": [36.0],
            "fgm": [10.0], "fga": [20.0], "fg_pct": [0.5],
            "fg3m": [3.0], "fg3a": [8.0], "fg3_pct": [0.375],
            "ftm": [5.0], "fta": [6.0], "ft_pct": [0.833],
            "oreb": [1.0], "dreb": [6.0], "reb": [7.0],
            "ast": [8.0], "stl": [2.0], "blk": [1.0],
            "tov": [3.0], "pf": [2.0], "pts": [28.0],
            "plus_minus": [12.0],
        })
        result = RawPlayerGameLogSchema.validate(df)
        assert result.shape[0] == 1

    def test_player_id_must_be_positive(self) -> None:
        df = pl.DataFrame({
            "season_id": ["22024"],
            "player_id": [-1],
            "game_id": ["001"],
            "game_date": ["2024-10-22"],
            "matchup": ["LAL vs. BOS"],
            "wl": [None], "min": [None],
            "fgm": [None], "fga": [None], "fg_pct": [None],
            "fg3m": [None], "fg3a": [None], "fg3_pct": [None],
            "ftm": [None], "fta": [None], "ft_pct": [None],
            "oreb": [None], "dreb": [None], "reb": [None],
            "ast": [None], "stl": [None], "blk": [None],
            "tov": [None], "pf": [None], "pts": [None],
            "plus_minus": [None],
        })
        with pytest.raises(pa_errors.SchemaError):
            RawPlayerGameLogSchema.validate(df)


class TestRawTeamGameLogSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_league_game_log_row())
        result = RawTeamGameLogSchema.validate(df)
        assert result.shape[0] == 1


# -- RawDraftHistorySchema ----------------------------------------------------


class TestRawDraftHistorySchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame({
            "person_id": [2544],
            "player_name": ["LeBron James"],
            "season": ["2003"],
            "round_number": [1],
            "round_pick": [1],
            "overall_pick": [1],
            "draft_type": ["Draft"],
            "team_id": [1610612739],
            "team_city": ["Cleveland"],
            "team_name": ["Cavaliers"],
            "team_abbreviation": ["CLE"],
            "organization": [None],
            "organization_type": [None],
            "player_profile_flag": [1],
        })
        result = RawDraftHistorySchema.validate(df)
        assert result.shape[0] == 1

    def test_person_id_must_be_positive(self) -> None:
        df = pl.DataFrame({
            "person_id": [-1],
            "player_name": [None], "season": [None],
            "round_number": [None], "round_pick": [None],
            "overall_pick": [None], "draft_type": [None],
            "team_id": [None], "team_city": [None],
            "team_name": [None], "team_abbreviation": [None],
            "organization": [None], "organization_type": [None],
            "player_profile_flag": [None],
        })
        with pytest.raises(pa_errors.SchemaError):
            RawDraftHistorySchema.validate(df)
