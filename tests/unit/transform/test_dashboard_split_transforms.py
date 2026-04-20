from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts._registry import (
    FactPlayerYoyDetailTransformer,
)
from nbadb.transform.facts.fact_player_clutch_detail import (
    FactPlayerClutchDetailTransformer,
)
from nbadb.transform.facts.fact_player_game_splits_detail import (
    FactPlayerGameSplitsDetailTransformer,
)
from nbadb.transform.facts.fact_player_general_splits_detail import (
    FactPlayerGeneralSplitsDetailTransformer,
)
from nbadb.transform.facts.fact_player_last_n_detail import (
    FactPlayerLastNDetailTransformer,
)
from nbadb.transform.facts.fact_player_shooting_splits_detail import (
    FactPlayerShootingSplitsDetailTransformer,
)
from nbadb.transform.facts.fact_player_team_perf_detail import (
    FactPlayerTeamPerfDetailTransformer,
)
from nbadb.transform.facts.fact_team_general_splits_detail import (
    FactTeamGeneralSplitsDetailTransformer,
)
from nbadb.transform.facts.fact_team_shooting_splits_detail import (
    FactTeamShootingSplitsDetailTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _player_row() -> dict:
    """Minimal row compatible with dashboard player split staging tables."""
    return {
        "player_id": 201566,
        "team_id": 1610612738,
        "season_year": "2024-25",
        "gp": 50,
        "w": 30,
        "l": 20,
        "min": 35.5,
        "pts": 22.5,
    }


def _team_row() -> dict:
    """Minimal row compatible with dashboard team split staging tables."""
    return {
        "team_id": 1610612738,
        "season_year": "2024-25",
        "gp": 50,
        "w": 30,
        "l": 20,
        "min": 240.0,
        "pts": 111.0,
    }


def _frame(row: dict) -> pl.LazyFrame:
    return pl.DataFrame({k: [v] for k, v in row.items()}).lazy()


def _register_all(depends_on: list[str], row_factory) -> dict[str, pl.LazyFrame]:
    """Build staging dict with one row per dependency."""
    return {dep: _frame(row_factory()) for dep in depends_on}


# ---------------------------------------------------------------------------
# Player Clutch Detail
# ---------------------------------------------------------------------------
class TestFactPlayerClutchDetail:
    def test_output_table(self) -> None:
        t = FactPlayerClutchDetailTransformer()
        assert t.output_table == "fact_player_clutch_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerClutchDetailTransformer()
        assert len(t.depends_on) == 11

    def test_depends_on_contents(self) -> None:
        t = FactPlayerClutchDetailTransformer()
        assert "stg_player_clutch_overall" in t.depends_on
        assert "stg_player_clutch_last5min_5pt" in t.depends_on

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerClutchDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerClutchDetailTransformer(), staging)
        assert result.shape[0] == 11
        assert "clutch_window" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerClutchDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerClutchDetailTransformer(), staging)
        windows = set(result["clutch_window"].to_list())
        assert "overall" in windows
        assert "last5min_5pt" in windows
        assert "last5min_pm5" in windows
        assert len(windows) == 11

    def test_subset_of_sources(self) -> None:
        """SQL uses UNION ALL BY NAME so all depends_on must be registered."""
        staging = _register_all(FactPlayerClutchDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerClutchDetailTransformer(), staging)
        assert result["player_id"].to_list() == [201566] * 11


# ---------------------------------------------------------------------------
# Player Game Splits Detail
# ---------------------------------------------------------------------------
class TestFactPlayerGameSplitsDetail:
    def test_output_table(self) -> None:
        t = FactPlayerGameSplitsDetailTransformer()
        assert t.output_table == "fact_player_game_splits_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerGameSplitsDetailTransformer()
        assert len(t.depends_on) == 5

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerGameSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerGameSplitsDetailTransformer(), staging)
        assert result.shape[0] == 5
        assert "split_type" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerGameSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerGameSplitsDetailTransformer(), staging)
        expected = {"actual_margin", "by_half", "by_period", "score_margin", "game_overall"}
        assert set(result["split_type"].to_list()) == expected


# ---------------------------------------------------------------------------
# Player General Splits Detail
# ---------------------------------------------------------------------------
class TestFactPlayerGeneralSplitsDetail:
    def test_output_table(self) -> None:
        t = FactPlayerGeneralSplitsDetailTransformer()
        assert t.output_table == "fact_player_general_splits_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerGeneralSplitsDetailTransformer()
        assert len(t.depends_on) == 7

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerGeneralSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerGeneralSplitsDetailTransformer(), staging)
        assert result.shape[0] == 7
        assert "split_type" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerGeneralSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerGeneralSplitsDetailTransformer(), staging)
        expected = {
            "days_rest",
            "location",
            "month",
            "general_overall",
            "pre_post_allstar",
            "starting_pos",
            "wins_losses",
        }
        assert set(result["split_type"].to_list()) == expected


# ---------------------------------------------------------------------------
# Player Last N Detail
# ---------------------------------------------------------------------------
class TestFactPlayerLastNDetail:
    def test_output_table(self) -> None:
        t = FactPlayerLastNDetailTransformer()
        assert t.output_table == "fact_player_last_n_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerLastNDetailTransformer()
        assert len(t.depends_on) == 6

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerLastNDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerLastNDetailTransformer(), staging)
        assert result.shape[0] == 6
        assert "window_size" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerLastNDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerLastNDetailTransformer(), staging)
        expected = {"game_number", "last10", "last15", "last20", "last5", "overall"}
        assert set(result["window_size"].to_list()) == expected


# ---------------------------------------------------------------------------
# Player Shooting Splits Detail
# ---------------------------------------------------------------------------
class TestFactPlayerShootingSplitsDetail:
    def test_output_table(self) -> None:
        t = FactPlayerShootingSplitsDetailTransformer()
        assert t.output_table == "fact_player_shooting_splits_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerShootingSplitsDetailTransformer()
        assert len(t.depends_on) == 8

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerShootingSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerShootingSplitsDetailTransformer(), staging)
        assert result.shape[0] == 8
        assert "shooting_split" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerShootingSplitsDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerShootingSplitsDetailTransformer(), staging)
        expected = {
            "assisted_by",
            "assisted_shot",
            "overall",
            "by_5ft",
            "by_8ft",
            "by_area",
            "by_type",
            "type_summary",
        }
        assert set(result["shooting_split"].to_list()) == expected


# ---------------------------------------------------------------------------
# Player Team Perf Detail
# ---------------------------------------------------------------------------
class TestFactPlayerTeamPerfDetail:
    def test_output_table(self) -> None:
        t = FactPlayerTeamPerfDetailTransformer()
        assert t.output_table == "fact_player_team_perf_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerTeamPerfDetailTransformer()
        assert len(t.depends_on) == 4

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerTeamPerfDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerTeamPerfDetailTransformer(), staging)
        assert result.shape[0] == 4
        assert "perf_context" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerTeamPerfDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerTeamPerfDetailTransformer(), staging)
        expected = {"overall", "pts_scored", "pts_against", "score_diff"}
        assert set(result["perf_context"].to_list()) == expected


# ---------------------------------------------------------------------------
# Player YoY Detail
# ---------------------------------------------------------------------------
class TestFactPlayerYoyDetail:
    def test_output_table(self) -> None:
        t = FactPlayerYoyDetailTransformer()
        assert t.output_table == "fact_player_yoy_detail"

    def test_depends_on_count(self) -> None:
        t = FactPlayerYoyDetailTransformer()
        assert len(t.depends_on) == 2

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactPlayerYoyDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerYoyDetailTransformer(), staging)
        assert result.shape[0] == 2
        assert "yoy_type" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactPlayerYoyDetailTransformer.depends_on, _player_row)
        result = _run(FactPlayerYoyDetailTransformer(), staging)
        assert set(result["yoy_type"].to_list()) == {"by_year", "overall"}


# ---------------------------------------------------------------------------
# Team General Splits Detail
# ---------------------------------------------------------------------------
class TestFactTeamGeneralSplitsDetail:
    def test_output_table(self) -> None:
        t = FactTeamGeneralSplitsDetailTransformer()
        assert t.output_table == "fact_team_general_splits_detail"

    def test_depends_on_count(self) -> None:
        t = FactTeamGeneralSplitsDetailTransformer()
        assert len(t.depends_on) == 6

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactTeamGeneralSplitsDetailTransformer.depends_on, _team_row)
        result = _run(FactTeamGeneralSplitsDetailTransformer(), staging)
        assert result.shape[0] == 6
        assert "split_type" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactTeamGeneralSplitsDetailTransformer.depends_on, _team_row)
        result = _run(FactTeamGeneralSplitsDetailTransformer(), staging)
        expected = {
            "days_rest",
            "location",
            "month",
            "general_overall",
            "pre_post_allstar",
            "wins_losses",
        }
        assert set(result["split_type"].to_list()) == expected

    def test_no_starting_pos_unlike_player(self) -> None:
        """Team general splits don't include starting_pos (players-only split)."""
        t = FactTeamGeneralSplitsDetailTransformer()
        assert "stg_team_split_starting_pos" not in t.depends_on


# ---------------------------------------------------------------------------
# Team Shooting Splits Detail
# ---------------------------------------------------------------------------
class TestFactTeamShootingSplitsDetail:
    def test_output_table(self) -> None:
        t = FactTeamShootingSplitsDetailTransformer()
        assert t.output_table == "fact_team_shooting_splits_detail"

    def test_depends_on_count(self) -> None:
        t = FactTeamShootingSplitsDetailTransformer()
        assert len(t.depends_on) == 7

    def test_transform_unions_all_sources(self) -> None:
        staging = _register_all(FactTeamShootingSplitsDetailTransformer.depends_on, _team_row)
        result = _run(FactTeamShootingSplitsDetailTransformer(), staging)
        assert result.shape[0] == 7
        assert "shooting_split" in result.columns

    def test_discriminator_values(self) -> None:
        staging = _register_all(FactTeamShootingSplitsDetailTransformer.depends_on, _team_row)
        result = _run(FactTeamShootingSplitsDetailTransformer(), staging)
        expected = {
            "assisted_by",
            "assisted_shot",
            "overall",
            "by_5ft",
            "by_8ft",
            "by_area",
            "by_type",
        }
        assert set(result["shooting_split"].to_list()) == expected

    def test_no_type_summary_unlike_player(self) -> None:
        """Team shooting splits lack type_summary (player-only split)."""
        t = FactTeamShootingSplitsDetailTransformer()
        assert "stg_team_shoot_type_summary" not in t.depends_on


# ---------------------------------------------------------------------------
# Cross-cutting: all transforms share SqlTransformer mechanics
# ---------------------------------------------------------------------------
ALL_TRANSFORMS = [
    FactPlayerClutchDetailTransformer,
    FactPlayerGameSplitsDetailTransformer,
    FactPlayerGeneralSplitsDetailTransformer,
    FactPlayerLastNDetailTransformer,
    FactPlayerShootingSplitsDetailTransformer,
    FactPlayerTeamPerfDetailTransformer,
    FactPlayerYoyDetailTransformer,
    FactTeamGeneralSplitsDetailTransformer,
    FactTeamShootingSplitsDetailTransformer,
]


@pytest.mark.parametrize(
    "cls",
    ALL_TRANSFORMS,
    ids=[c.__name__ for c in ALL_TRANSFORMS],
)
def test_sql_is_non_empty(cls) -> None:
    assert cls._SQL.strip(), f"{cls.__name__}._SQL should be non-empty"


@pytest.mark.parametrize(
    "cls",
    ALL_TRANSFORMS,
    ids=[c.__name__ for c in ALL_TRANSFORMS],
)
def test_no_connection_before_injection(cls) -> None:
    t = cls()
    with pytest.raises(RuntimeError, match="No DuckDB connection"):
        t.conn  # noqa: B018
