from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.star.dim_game import DimGameSchema
from nbadb.schemas.star.dim_player import DimPlayerSchema
from nbadb.schemas.star.dim_team import DimTeamSchema
from nbadb.schemas.star.fact_player_game_traditional import (
    FactPlayerGameTraditionalSchema,
)

# -- DimPlayerSchema ----------------------------------------------------------


def _dim_player_row(**overrides: object) -> dict:
    base = {
        "player_sk": 1,
        "player_id": 2544,
        "full_name": "LeBron James",
        "first_name": "LeBron",
        "last_name": "James",
        "is_active": True,
        "team_id": 1610612747,
        "position": "Forward",
        "jersey_number": "23",
        "height": "6-9",
        "weight": 250,
        "birth_date": "1984-12-30",
        "country": "USA",
        "college_id": None,
        "draft_year": 2003,
        "draft_round": 1,
        "draft_number": 1,
        "from_year": 2003,
        "to_year": 2024,
        "valid_from": "2003-04",
        "valid_to": None,
        "is_current": True,
    }
    base.update(overrides)
    return base


class TestDimPlayerSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_dim_player_row())
        result = DimPlayerSchema.validate(df)
        assert result.shape[0] == 1

    def test_scd2_multiple_records(self) -> None:
        rows = [
            _dim_player_row(
                player_sk=1, valid_from="2018-19",
                valid_to="2019-20", is_current=False,
                team_id=1610612739,
            ),
            _dim_player_row(
                player_sk=2, valid_from="2019-20",
                valid_to=None, is_current=True,
                team_id=1610612747,
            ),
        ]
        df = pl.DataFrame(rows)
        result = DimPlayerSchema.validate(df)
        assert result.shape[0] == 2

    def test_player_sk_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_player_row(player_sk=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_player_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_player_row(player_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_full_name_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_player_row(full_name=None))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_weight_must_be_non_negative(self) -> None:
        df = pl.DataFrame(_dim_player_row(weight=-10.0))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_is_current_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_player_row(is_current=None))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_team_id_fk_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_player_row(team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_team_id_nullable(self) -> None:
        df = pl.DataFrame(_dim_player_row(team_id=None))
        result = DimPlayerSchema.validate(df)
        assert result.shape[0] == 1

    def test_nullable_scd2_fields(self) -> None:
        df = pl.DataFrame(_dim_player_row(
            valid_to=None, college_id=None,
        ))
        result = DimPlayerSchema.validate(df)
        assert result.shape[0] == 1

    def test_valid_from_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_player_row(valid_from=None))
        with pytest.raises(pa_errors.SchemaError):
            DimPlayerSchema.validate(df)

    def test_pk_uniqueness(self) -> None:
        rows = [
            _dim_player_row(player_sk=1, is_current=False),
            _dim_player_row(player_sk=2, is_current=True),
        ]
        df = pl.DataFrame(rows)
        result = DimPlayerSchema.validate(df)
        assert result["player_sk"].n_unique() == result.shape[0]


# -- DimTeamSchema ------------------------------------------------------------


def _dim_team_row(**overrides: object) -> dict:
    base = {
        "team_id": 1610612747,
        "abbreviation": "LAL",
        "full_name": "Los Angeles Lakers",
        "city": "Los Angeles",
        "state": "California",
        "arena": "Crypto.com Arena",
        "year_founded": 1947,
        "conference": "West",
        "division": "Pacific",
    }
    base.update(overrides)
    return base


class TestDimTeamSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_dim_team_row())
        result = DimTeamSchema.validate(df)
        assert result.shape[0] == 1

    def test_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_team_row(team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimTeamSchema.validate(df)

    def test_abbreviation_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_team_row(abbreviation=None))
        with pytest.raises(pa_errors.SchemaError):
            DimTeamSchema.validate(df)

    def test_full_name_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_team_row(full_name=None))
        with pytest.raises(pa_errors.SchemaError):
            DimTeamSchema.validate(df)

    def test_year_founded_must_be_after_1900(self) -> None:
        df = pl.DataFrame(_dim_team_row(year_founded=1800))
        with pytest.raises(pa_errors.SchemaError):
            DimTeamSchema.validate(df)

    def test_nullable_fields(self) -> None:
        df = pl.DataFrame(_dim_team_row(
            city=None, state=None, arena=None,
            conference=None, division=None, year_founded=None,
        ))
        result = DimTeamSchema.validate(df)
        assert result.shape[0] == 1

    def test_multiple_teams(self) -> None:
        rows = [
            _dim_team_row(team_id=1610612747, abbreviation="LAL"),
            _dim_team_row(team_id=1610612738, abbreviation="BOS",
                          full_name="Boston Celtics", city="Boston"),
        ]
        df = pl.DataFrame(rows)
        result = DimTeamSchema.validate(df)
        assert result.shape[0] == 2


# -- DimGameSchema ------------------------------------------------------------


def _dim_game_row(**overrides: object) -> dict:
    base = {
        "game_id": "0022400001",
        "game_date": "2024-10-22",
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "home_team_id": 1610612747,
        "visitor_team_id": 1610612738,
        "matchup": "LAL vs. BOS",
        "arena_name": "Crypto.com Arena",
        "arena_city": "Los Angeles",
    }
    base.update(overrides)
    return base


class TestDimGameSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_dim_game_row())
        result = DimGameSchema.validate(df)
        assert result.shape[0] == 1

    def test_game_id_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_game_row(game_id=None))
        with pytest.raises(pa_errors.SchemaError):
            DimGameSchema.validate(df)

    def test_game_date_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_game_row(game_date=None))
        with pytest.raises(pa_errors.SchemaError):
            DimGameSchema.validate(df)

    def test_season_year_not_nullable(self) -> None:
        df = pl.DataFrame(_dim_game_row(season_year=None))
        with pytest.raises(pa_errors.SchemaError):
            DimGameSchema.validate(df)

    def test_home_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_game_row(home_team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimGameSchema.validate(df)

    def test_visitor_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_dim_game_row(visitor_team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            DimGameSchema.validate(df)

    def test_nullable_fields(self) -> None:
        df = pl.DataFrame(_dim_game_row(
            season_type=None, home_team_id=None, visitor_team_id=None,
            matchup=None, arena_name=None, arena_city=None,
        ))
        result = DimGameSchema.validate(df)
        assert result.shape[0] == 1


# -- FactPlayerGameTraditionalSchema ------------------------------------------


def _fact_player_game_trad_row(**overrides: object) -> dict:
    base = {
        "game_id": "0022400001",
        "player_id": 2544,
        "team_id": 1610612747,
        "min": 36.0,
        "pts": 28,
        "reb": 7,
        "ast": 8,
        "stl": 2,
        "blk": 1,
        "tov": 3,
        "pf": 2,
        "fgm": 10,
        "fga": 20,
        "fg_pct": 0.5,
        "fg3m": 3,
        "fg3a": 8,
        "fg3_pct": 0.375,
        "ftm": 5,
        "fta": 6,
        "ft_pct": 0.833,
        "oreb": 1,
        "dreb": 6,
        "plus_minus": 12.0,
        "season_year": "2024-25",
        "start_position": "F",
    }
    base.update(overrides)
    return base


class TestFactPlayerGameTraditionalSchema:
    def test_valid_data(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row())
        result = FactPlayerGameTraditionalSchema.validate(df)
        assert result.shape[0] == 1

    def test_game_id_not_nullable(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(game_id=None))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_player_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(player_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_team_id_must_be_positive(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(team_id=-1))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_stat_counts_must_be_non_negative(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(pts=-5))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_min_must_be_non_negative(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(min=-1.0))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_nullable_stat_fields(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(
            pts=None, reb=None, ast=None, min=None,
            fg_pct=None, fg3_pct=None, ft_pct=None,
        ))
        result = FactPlayerGameTraditionalSchema.validate(df)
        assert result.shape[0] == 1

    def test_plus_minus_allows_negative(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(plus_minus=-15.0))
        result = FactPlayerGameTraditionalSchema.validate(df)
        assert result.shape[0] == 1

    def test_season_year_not_nullable(self) -> None:
        df = pl.DataFrame(_fact_player_game_trad_row(season_year=None))
        with pytest.raises(pa_errors.SchemaError):
            FactPlayerGameTraditionalSchema.validate(df)

    def test_multiple_rows(self) -> None:
        rows = [
            _fact_player_game_trad_row(player_id=2544, pts=28),
            _fact_player_game_trad_row(player_id=203507, pts=35),
        ]
        df = pl.DataFrame(rows)
        result = FactPlayerGameTraditionalSchema.validate(df)
        assert result.shape[0] == 2
