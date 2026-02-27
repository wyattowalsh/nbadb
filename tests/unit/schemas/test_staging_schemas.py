from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.staging.box_score import StagingBoxScoreTraditionalPlayerSchema
from nbadb.schemas.staging.draft import StagingDraftHistorySchema
from nbadb.schemas.staging.game_log import StagingLeagueGameLogSchema
from nbadb.schemas.staging.player import (
    StagingCommonAllPlayersSchema,
    StagingPlayerIndexSchema,
)

# -- StagingCommonAllPlayersSchema --------------------------------------------


def _staging_common_all_players_row(**overrides: object) -> dict:
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


class TestStagingCommonAllPlayersSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_staging_common_all_players_row())
        result = StagingCommonAllPlayersSchema.validate(df)
        assert result.shape[0] == 1

    def test_person_id_required(self) -> None:
        df = pl.DataFrame(_staging_common_all_players_row(person_id=None))
        with pytest.raises(pa_errors.SchemaError):
            StagingCommonAllPlayersSchema.validate(df)

    def test_display_first_last_not_nullable(self) -> None:
        df = pl.DataFrame(
            _staging_common_all_players_row(display_first_last=None)
        )
        with pytest.raises(pa_errors.SchemaError):
            StagingCommonAllPlayersSchema.validate(df)


# -- StagingPlayerIndexSchema -------------------------------------------------


def _staging_player_index_row(**overrides: object) -> dict:
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


class TestStagingPlayerIndexSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_staging_player_index_row())
        result = StagingPlayerIndexSchema.validate(df)
        assert result.shape[0] == 1

    def test_pts_must_be_non_negative(self) -> None:
        df = pl.DataFrame(_staging_player_index_row(pts=-5.0))
        with pytest.raises(pa_errors.SchemaError):
            StagingPlayerIndexSchema.validate(df)

    def test_nullable_stats(self) -> None:
        df = pl.DataFrame(
            _staging_player_index_row(pts=None, reb=None, ast=None)
        )
        result = StagingPlayerIndexSchema.validate(df)
        assert result.shape[0] == 1


# -- StagingLeagueGameLogSchema -----------------------------------------------


def _staging_league_game_log_row(**overrides: object) -> dict:
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
        "fgm": 40.0, "fga": 85.0, "fg_pct": 0.471,
        "fg3m": 12.0, "fg3a": 35.0, "fg3_pct": 0.343,
        "ftm": 20.0, "fta": 25.0, "ft_pct": 0.800,
        "oreb": 10.0, "dreb": 35.0, "reb": 45.0,
        "ast": 25.0, "stl": 8.0, "blk": 5.0,
        "tov": 12.0, "pf": 18.0, "pts": 112.0,
        "plus_minus": 8.0,
        "video_available": 1,
    }
    base.update(overrides)
    return base


class TestStagingLeagueGameLogSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_staging_league_game_log_row())
        result = StagingLeagueGameLogSchema.validate(df)
        assert result.shape[0] == 1

    def test_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_staging_league_game_log_row(team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            StagingLeagueGameLogSchema.validate(df)

    def test_season_id_not_nullable(self) -> None:
        df = pl.DataFrame(_staging_league_game_log_row(season_id=None))
        with pytest.raises(pa_errors.SchemaError):
            StagingLeagueGameLogSchema.validate(df)

    def test_nullable_stat_fields(self) -> None:
        df = pl.DataFrame(
            _staging_league_game_log_row(pts=None, reb=None, plus_minus=None)
        )
        result = StagingLeagueGameLogSchema.validate(df)
        assert result.shape[0] == 1


# -- StagingDraftHistorySchema ------------------------------------------------


class TestStagingDraftHistorySchema:
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
        result = StagingDraftHistorySchema.validate(df)
        assert result.shape[0] == 1

    def test_person_id_not_nullable(self) -> None:
        df = pl.DataFrame({
            "person_id": [None],
            "player_name": ["Test"],
            "season": ["2003"],
            "round_number": [1], "round_pick": [1],
            "overall_pick": [1], "draft_type": [None],
            "team_id": [None], "team_city": [None],
            "team_name": [None], "team_abbreviation": [None],
            "organization": [None], "organization_type": [None],
            "player_profile_flag": [None],
        })
        with pytest.raises(pa_errors.SchemaError):
            StagingDraftHistorySchema.validate(df)

    def test_round_number_must_be_1_or_2(self) -> None:
        df = pl.DataFrame({
            "person_id": [100],
            "player_name": ["Test"],
            "season": ["2003"],
            "round_number": [5],
            "round_pick": [1], "overall_pick": [1],
            "draft_type": [None], "team_id": [None],
            "team_city": [None], "team_name": [None],
            "team_abbreviation": [None], "organization": [None],
            "organization_type": [None], "player_profile_flag": [None],
        })
        with pytest.raises(pa_errors.SchemaError):
            StagingDraftHistorySchema.validate(df)


# -- StagingBoxScoreTraditionalPlayerSchema -----------------------------------


def _staging_box_score_trad_player_row(**overrides: object) -> dict:
    base = {
        "game_id": "0022400001",
        "team_id": 1610612747,
        "team_abbreviation": "LAL",
        "team_city": "Los Angeles",
        "player_id": 2544,
        "player_name": "LeBron James",
        "nickname": "King",
        "start_position": "F",
        "comment": None,
        "min": "36:00",
        "fgm": 10, "fga": 20, "fg_pct": 0.5,
        "fg3m": 3, "fg3a": 8, "fg3_pct": 0.375,
        "ftm": 5, "fta": 6, "ft_pct": 0.833,
        "oreb": 1, "dreb": 6, "reb": 7,
        "ast": 8, "stl": 2, "blk": 1,
        "tov": 3, "pf": 2, "pts": 28,
        "plus_minus": 12.0,
    }
    base.update(overrides)
    return base


class TestStagingBoxScoreTraditionalPlayerSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_staging_box_score_trad_player_row())
        result = StagingBoxScoreTraditionalPlayerSchema.validate(df)
        assert result.shape[0] == 1

    def test_game_id_not_nullable(self) -> None:
        df = pl.DataFrame(_staging_box_score_trad_player_row(game_id=None))
        with pytest.raises(pa_errors.SchemaError):
            StagingBoxScoreTraditionalPlayerSchema.validate(df)

    def test_player_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_staging_box_score_trad_player_row(player_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            StagingBoxScoreTraditionalPlayerSchema.validate(df)

    def test_nullable_stat_fields(self) -> None:
        df = pl.DataFrame(
            _staging_box_score_trad_player_row(
                pts=None, reb=None, ast=None, min=None
            )
        )
        result = StagingBoxScoreTraditionalPlayerSchema.validate(df)
        assert result.shape[0] == 1
